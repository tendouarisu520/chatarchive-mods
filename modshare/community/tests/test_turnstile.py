import io
import json
import re
import urllib.error
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings


@override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SITE_KEY='public-test-sitekey',
    TURNSTILE_SECRET_KEY='private-test-secret', TURNSTILE_HOSTNAMES=['chatarchivemods.org'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class TurnstileGateTests(TestCase):
    def test_client_error_report_records_only_safe_code_and_action(self):
        with self.assertLogs('community.turnstile',level='WARNING') as logs:
            response=self.post('verification-report',{'code':'200500','action':'login','token':'never-log-this'})
        self.assertEqual(response.status_code,200)
        self.assertIn('200500',str(logs.output))
        self.assertNotIn('never-log-this',str(logs.output))
        self.assertEqual(self.post('verification-report',{'code':'private-test-secret','action':'login'}).status_code,400)

    def test_server_rejection_is_logged_without_credentials(self):
        with self.assertLogs('community.turnstile',level='WARNING') as logs, patch('urllib.request.urlopen',return_value=self.answer(False,**{'error-codes':['timeout-or-duplicate']})):
            self.post('send-code',{'email':'new@example.com','turnstile_token':'do-not-log-token'})
        self.assertIn('timeout-or-duplicate',str(logs.output))
        self.assertNotIn('do-not-log-token',str(logs.output))
        self.assertNotIn('private-test-secret',str(logs.output))
    def post(self, endpoint, body):
        return self.client.post('/api/auth/' + endpoint + '/', json.dumps(body), content_type='application/json')

    def answer(self, success=True, hostname='chatarchivemods.org', action='register', **extra):
        return io.BytesIO(json.dumps({'success': success, 'hostname': hostname, 'action': action, **extra}).encode())

    def registration(self, token='', code='000000'):
        return {'email':'new@example.com', 'password':'Long-test-secret-927!',
            'confirm':'Long-test-secret-927!', 'code':code, 'turnstile_token':token}

    def test_missing_token_does_not_send_email(self):
        response = self.post('send-code', {'email':'new@example.com'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'human_verification_required')
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_token_does_not_create_account(self):
        response = self.post('register', self.registration())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(email='new@example.com').exists())

    def test_login_and_password_reset_require_verification(self):
        get_user_model().objects.create_user(email='new@example.com', password='Long-test-secret-927!')
        self.assertEqual(self.post('login', self.registration()).status_code, 403)
        self.assertEqual(self.post('reset-password', self.registration()).status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_hostname_or_action_cannot_send_mail(self):
        for hostname, action in [('other.example','register'), ('chatarchivemods.org','login')]:
            with self.subTest(hostname=hostname, action=action), patch('urllib.request.urlopen', return_value=self.answer(hostname=hostname,action=action)):
                response = self.post('send-code', {'email':'new@example.com','turnstile_token':'valid-looking'})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_expired_or_replayed_token_does_not_register(self):
        with patch('urllib.request.urlopen', side_effect=[self.answer(), self.answer(False, **{'error-codes':['timeout-or-duplicate']})]):
            self.assertEqual(self.post('send-code', {'email':'new@example.com','turnstile_token':'first-token'}).status_code, 200)
            code = re.search(r'验证码是：(\d{6})', mail.outbox[-1].body).group(1)
            self.assertEqual(self.post('register', self.registration('first-token',code)).status_code, 403)
        self.assertFalse(get_user_model().objects.filter(email='new@example.com').exists())

    def test_separate_tokens_allow_verified_email_registration(self):
        with patch('urllib.request.urlopen', side_effect=[self.answer(),self.answer()]) as verify:
            self.assertEqual(self.post('send-code', {'email':'new@example.com','turnstile_token':'send-token'}).status_code, 200)
            code = re.search(r'验证码是：(\d{6})', mail.outbox[-1].body).group(1)
            response = self.post('register', self.registration('register-token',code))
            self.assertEqual(response.status_code, 201)
            self.assertEqual(get_user_model().objects.get(email='new@example.com').role, 'user')
            self.assertEqual(verify.call_count, 2)
            requests = [json.loads(call.args[0].data) for call in verify.call_args_list]
            self.assertEqual([body['response'] for body in requests], ['send-token','register-token'])
            self.assertTrue(all(body['secret']=='private-test-secret' for body in requests))

    def test_verification_network_failure_does_not_bypass_gate(self):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('private-test-secret')):
            response = self.post('send-code', {'email':'new@example.com','turnstile_token':'token'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-test-secret', response.content.decode())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_token_types_are_rejected_without_network(self):
        for token in (None, True, ['token'], 'x'*2049):
            with self.subTest(token_type=type(token).__name__), patch('urllib.request.urlopen') as verify:
                response = self.post('send-code', {'email':'new@example.com','turnstile_token':token})
                self.assertEqual(response.status_code, 403)
                verify.assert_not_called()

    def test_browser_receives_only_sitekey_and_auth_csp_allowlist(self):
        response = self.client.get('/register/')
        self.assertContains(response, 'public-test-sitekey')
        self.assertNotContains(response, 'private-test-secret')
        self.assertIn('https://challenges.cloudflare.com', response['Content-Security-Policy'])
        self.assertNotIn('https://challenges.cloudflare.com', self.client.get('/')['Content-Security-Policy'])

    @override_settings(TURNSTILE_ENABLED=False)
    def test_loopback_preview_without_turnstile_still_works(self):
        with patch('urllib.request.urlopen') as verify:
            self.assertEqual(self.post('send-code', {'email':'new@example.com'}).status_code, 200)
            verify.assert_not_called()
