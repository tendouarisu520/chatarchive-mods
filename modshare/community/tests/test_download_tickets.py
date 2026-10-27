import json
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from community.models import DownloadEvent
from . import test_resources as fixture


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DownloadTicketTests(TestCase):
    setUp = fixture.ResourceTests.setUp
    tearDown = fixture.ResourceTests.tearDown
    file = fixture.ResourceTests.file
    submit = fixture.ResourceTests.submit
    created = fixture.ResourceTests.created
    approve = fixture.ResourceTests.approve

    def issue(self, revision, client=None, review=False):
        response = (client or self.client).post(f'/api/downloads/{revision}/ticket/',
                json.dumps({'review':review}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['data']['url']

    def test_cookie_less_download_and_range_with_scoped_ticket(self):
        item=self.created();revision=self.approve(item)
        url=self.issue(revision)
        visitor=Client()
        response=visitor.get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(b''.join(response.streaming_content),b'{"preset":"hello"}')
        self.assertEqual(DownloadEvent.objects.count(),1)
        partial=visitor.get(url,HTTP_RANGE='bytes=2-7')
        self.assertEqual(partial.status_code,206)
        self.assertEqual(b''.join(partial.streaming_content),b'{"preset":"hello"}'[2:8])
        self.assertEqual(visitor.head(url).status_code,200)
        self.assertEqual(DownloadEvent.objects.count(),1)
        self.assertEqual(response['Referrer-Policy'],'no-referrer')

    def test_ticket_issuance_requires_login_and_cannot_borrow_other_account(self):
        item=self.created();revision=self.approve(item)
        self.assertEqual(Client().post(f'/api/downloads/{revision}/ticket/',{},content_type='application/json').status_code,401)
        url=self.issue(revision)
        self.assertEqual(self.reader.get(url).status_code,403)

    def test_forged_expired_and_wrong_file_tickets_are_rejected(self):
        first=self.created();revision=self.approve(first);url=self.issue(revision)
        query=parse_qs(urlsplit(url).query);token=query['ticket'][0]
        self.assertEqual(Client().get(urlsplit(url).path+'?ticket=invalid').status_code,403)
        second=self.created();other_revision=self.approve(second)
        self.assertEqual(Client().get(f'/download/{other_revision}/?ticket='+token).status_code,403)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+901):
            self.assertEqual(Client().get(url).status_code,410)

    def test_ban_and_password_reset_revoke_existing_tickets(self):
        item=self.created();revision=self.approve(item);url=self.issue(revision)
        self.member.banned_at=timezone.now();self.member.save(update_fields=['banned_at'])
        self.assertEqual(Client().get(url).status_code,403)
        self.member.banned_at=None;self.member.set_password('new-password-value');self.member.save()
        self.assertEqual(Client().get(url).status_code,403)

    def test_unpublish_and_role_changes_are_checked_after_issue(self):
        item=self.created();revision=self.approve(item);url=self.issue(revision,client=self.reader)
        self.staff.post(f"/api/manage/resources/{item['id']}/",json.dumps({'action':'unpublish','reason':'测试'}),content_type='application/json')
        self.assertEqual(Client().get(url).status_code,404)
        pending=self.created();private_revision=pending['latest_revision']['id']
        admin_url=self.issue(private_revision,client=self.staff,review=True)
        self.admin.role='user';self.admin.save(update_fields=['role'])
        self.assertEqual(Client().get(admin_url).status_code,404)

    def test_review_tickets_cannot_be_used_as_public_downloads_or_by_non_reviewers(self):
        item=self.created();revision=self.approve(item)
        response=self.reader.post(f'/api/downloads/{revision}/ticket/',json.dumps({'review':True}),content_type='application/json')
        self.assertEqual(response.status_code,404)
        url=self.issue(revision,client=self.staff,review=True)
        response=Client().get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(b''.join(response.streaming_content),b'{"preset":"hello"}')
        self.assertEqual(DownloadEvent.objects.count(),0)
        self.assertEqual(Client().get(url.replace('/review-download/','/download/')).status_code,403)

    def test_ticket_creation_enforces_csrf(self):
        item=self.created();revision=self.approve(item)
        client=Client(enforce_csrf_checks=True);client.force_login(self.member)
        target=f'/api/downloads/{revision}/ticket/'
        self.assertEqual(client.post(target,'{}',content_type='application/json').status_code,403)
        client.get('/api/me/')
        response=client.post(target,'{}',content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['modcsrftoken'].value)
        self.assertEqual(response.status_code,200)
