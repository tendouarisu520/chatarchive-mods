import json
import re
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RegistrationGateTests(TestCase):
    def test_missing_verification_does_not_create_account(self):
        response = self.client.post('/api/auth/register/', json.dumps({
            'email': 'new@example.com', 'password': 'Long-test-secret-927!',
            'confirm': 'Long-test-secret-927!', 'code': '000000', 'display_name': '旅人',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email='new@example.com').exists())

    def test_guest_cannot_access_management(self):
        response = self.client.get('/api/manage/users/')
        self.assertEqual(response.status_code, 401)

    def send(self, email='new@example.com', purpose='register'):
        response = self.client.post('/api/auth/send-code/', json.dumps({'email': email, 'purpose': purpose}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return re.search(r'验证码是：(\d{6})', mail.outbox[-1].body).group(1)

    def register(self, email, code):
        return self.client.post('/api/auth/register/', json.dumps({
            'email': email, 'password': 'Long-test-secret-927!', 'confirm': 'Long-test-secret-927!',
            'display_name': '旅人', 'code': code, 'role': 'owner',
        }), content_type='application/json')

    def test_valid_code_creates_only_normal_user(self):
        code = self.send()
        response = self.register('new@example.com', code)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(get_user_model().objects.get(email='new@example.com').role, 'user')

    def test_email_case_cannot_create_second_account(self):
        code = self.send()
        self.assertEqual(self.register('NEW@example.com', code).status_code, 201)
        self.assertEqual(self.register('new@EXAMPLE.com', code).status_code, 409)
        self.assertEqual(get_user_model().objects.filter(email='new@example.com').count(), 1)

    def test_failed_code_attempts_persist(self):
        self.send()
        for _ in range(5):
            self.assertEqual(self.register('new@example.com', 'invalid').status_code, 400)
        self.assertEqual(self.register('new@example.com', 'invalid').status_code, 429)

    def test_reset_code_single_use_and_old_password_invalid(self):
        user = get_user_model().objects.create_user(email='new@example.com', password='original-long-secret')
        code = self.send(purpose='reset')
        body = json.dumps({'email': user.email, 'code': code, 'password': 'replacement-secret-932!', 'confirm': 'replacement-secret-932!'})
        self.assertEqual(self.client.post('/api/auth/reset-password/', body, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/reset-password/', body, content_type='application/json').status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password('replacement-secret-932!'))
        self.assertFalse(user.check_password('original-long-secret'))

    def test_csrf_cannot_be_skipped(self):
        response = Client(enforce_csrf_checks=True).post('/api/auth/login/', json.dumps({'email': 'a@example.com', 'password': 'long-secret'}), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'csrf_failed')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RoleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='owner@example.com', role='owner')
        self.admin = User.objects.create_user(email='admin@example.com', role='admin')
        self.member = User.objects.create_user(email='user@example.com')
        self.client.force_login(self.admin)

    def action(self, target, action, reason='测试原因'):
        return self.client.post(f'/api/manage/users/{target.id}/', json.dumps({'action': action, 'reason': reason}), content_type='application/json')

    def test_admin_cannot_grant_roles_or_ban_owner(self):
        self.assertEqual(self.action(self.member, 'promote').status_code, 403)
        self.assertEqual(self.action(self.owner, 'ban').status_code, 403)
        self.assertEqual(self.action(self.admin, 'ban').status_code, 403)

    def test_owner_can_appoint_and_dismiss_admin(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.action(self.member, 'promote').status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, 'admin')
        self.assertEqual(self.action(self.member, 'demote').status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, 'user')

    def test_revoked_role_loses_access_in_existing_session(self):
        owner_client = Client()
        owner_client.force_login(self.owner)
        self.assertEqual(owner_client.post(f'/api/manage/users/{self.admin.id}/', json.dumps({'action': 'demote'}), content_type='application/json').status_code, 200)
        self.assertEqual(self.client.get('/api/manage/audit/').status_code, 403)

    def test_admin_can_ban_user_but_email_remains_reserved(self):
        self.assertEqual(self.action(self.member, 'ban').status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.banned_at)
        self.assertTrue(get_user_model().objects.filter(email='user@example.com').exists())

    def test_database_rejects_second_owner(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create_user(email='second-owner@example.com', role='owner')
