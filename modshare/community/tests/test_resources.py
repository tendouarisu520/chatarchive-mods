import io
import json
import struct
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils import timezone


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ResourceTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-files-', dir=settings.DATA_DIR.parent)
        self.config = override_settings(PRIVATE_ROOT=Path(self.temp.name), MAX_STORAGE_BYTES=20_000_000_000)
        self.config.enable()
        User = get_user_model()
        self.member = User.objects.create_user(email='author@example.com')
        self.other = User.objects.create_user(email='reader@example.com')
        self.admin = User.objects.create_user(email='admin@example.com', role='admin')
        self.client.force_login(self.member)
        self.staff = Client()
        self.staff.force_login(self.admin)
        self.reader = Client()
        self.reader.force_login(self.other)

    def tearDown(self):
        self.config.disable()
        Path(self.temp.name).resolve().relative_to(settings.DATA_DIR.parent.resolve())
        self.temp.cleanup()

    def file(self, name='preset.json', content=b'{"preset":"hello"}'):
        return SimpleUploadedFile(name, content, content_type='application/octet-stream')

    def submit(self, title='投稿标题', file=None, category='presets'):
        return self.client.post('/api/uploads/', {'category': category, 'title': title,
                                'description': '这是文字介绍', 'file': file or self.file()})

    def created(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        return response.json()['data']

    def approve(self, item):
        revision = item['latest_revision']['id']
        response = self.staff.post(f'/api/manage/reviews/{revision}/', json.dumps({'action': 'approve'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return revision

    def test_upload_enters_review_not_public_list(self):
        item = self.created()
        self.assertEqual(item['latest_revision']['status'], 'pending')
        self.assertEqual(self.reader.get('/api/resources/').json()['data']['total'], 0)
        self.assertEqual(self.reader.get(f"/api/resources/{item['id']}/").status_code, 404)
        self.assertEqual(self.reader.get(f"/download/{item['latest_revision']['id']}/").status_code, 404)

    def test_approved_resource_downloads_original_bytes(self):
        item = self.created()
        revision = self.approve(item)
        published = self.reader.get(f"/api/resources/{item['id']}/").json()['data']
        self.assertEqual(published['file']['id'], revision)
        response = self.reader.get(f'/download/{revision}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'{"preset":"hello"}')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(Client().get(f'/download/{revision}/').status_code, 401)

    def test_banned_existing_session_cannot_upload_or_download_or_resume(self):
        item = self.created()
        revision = self.approve(item)
        self.assertEqual(self.staff.post(f'/api/manage/users/{self.member.id}/', json.dumps({'action': 'ban', 'reason': '违规'}), content_type='application/json').status_code, 200)
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(self.client.get(f'/download/{revision}/').status_code, 403)
        self.assertEqual(self.client.get(f'/download/{revision}/', HTTP_RANGE='bytes=0-4').status_code, 403)
        self.assertEqual(self.client.get(f"/download/{item['latest_revision']['id']}/").status_code, 403)

    def test_daily_sixth_upload_rejected_even_after_rejection(self):
        first = self.created()
        self.assertEqual(self.staff.post(f"/api/manage/reviews/{first['latest_revision']['id']}/", json.dumps({'action': 'reject', 'reason': '介绍不全'}), content_type='application/json').status_code, 200)
        for _ in range(4):
            self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.submit().status_code, 429)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['remaining'], 0)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.blob'))), 5)

    def test_quota_resets_at_beijing_midnight(self):
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        with patch('community.resources.timezone.now', return_value=yesterday):
            for _ in range(5):
                self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.submit().status_code, 201)

    def test_failed_validation_does_not_consume_quota(self):
        self.assertEqual(self.submit(file=self.file('evil.zip', b'not an archive'), category='characters').status_code, 400)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 0)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.blob'))), 0)

    def test_character_accepts_zip_but_rejects_preset(self):
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, 'w') as archive:
            archive.writestr('character.txt', '角色')
        self.assertEqual(self.submit(file=self.file('character.zip', zipped.getvalue()), category='characters').status_code, 201)
        self.assertEqual(self.submit(category='characters').status_code, 400)

    def test_preset_rejects_binary_and_executable_extension(self):
        self.assertEqual(self.submit(file=self.file('file.txt', b'\0binary')).status_code, 400)
        self.assertEqual(self.submit(file=self.file('file.exe', b'hello')).status_code, 400)

    def capk(self):
        name = '久岛鸥'.encode('utf-8')
        entry = b'manifest.json'
        body = b'{"schema_version":1}'
        return (b'KPAC' + struct.pack('<i', 1) + bytes([len(name)]) + name +
                struct.pack('<i', 1) + bytes([len(entry)]) + entry +
                struct.pack('<i', len(body)) + body)

    def test_capk_waits_for_review_then_downloads_original_bytes(self):
        content = self.capk()
        response = self.submit(file=self.file('久岛鸥.CAPK', content), category='characters')
        self.assertEqual(response.status_code, 201)
        item = response.json()['data']
        self.assertEqual(item['latest_revision']['status'], 'pending')
        self.assertEqual(self.reader.get('/api/resources/').json()['data']['total'], 0)
        revision = self.approve(item)
        downloaded = self.reader.get(f'/download/{revision}/')
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(b''.join(downloaded.streaming_content), content)
        self.assertIn('.CAPK', downloaded['Content-Disposition'])

    def test_capk_replacement_waits_for_review(self):
        original = self.submit(file=self.file('original.capk', self.capk()), category='characters')
        self.assertEqual(original.status_code, 201)
        item = original.json()['data']
        published_revision = self.approve(item)
        response = self.client.post(f"/api/resources/{item['id']}/revisions/", {
            'title': '新包', 'description': '介绍', 'file': self.file('replacement.capk', self.capk())})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['data']['latest_revision']['status'], 'pending')
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 2)
        public = self.reader.get(f"/api/resources/{item['id']}/").json()['data']
        self.assertEqual(public['file']['id'], published_revision)

    def test_invalid_capk_does_not_consume_quota_or_store_files(self):
        content = self.capk()
        invalid = [b'not a package', b'KPAC\x01\x00\x00\x00', content[:-1], content+b'extra',
                   b'KPAC'+struct.pack('<i', 2)+content[8:],
                   b'KPAC'+struct.pack('<i', 1)+b'\xff'*5,
                   b'KPAC'+struct.pack('<i', 1)+b'\x01x'+struct.pack('<i', 4097),
                   b'KPAC'+struct.pack('<i', 1)+b'\x01x'+struct.pack('<i', 1)+b'\x01f'+struct.pack('<i', -1)]
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, 'w') as archive:
            archive.writestr('role.json', '{}')
        invalid.append(zipped.getvalue())
        for body in invalid:
            with self.subTest(body=body[:16]):
                self.assertEqual(self.submit(file=self.file('broken.capk', body), category='characters').status_code, 400)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 0)
        self.assertEqual(list(Path(self.temp.name).glob('*.blob')), [])

    def test_capk_is_not_accepted_in_presets(self):
        self.assertEqual(self.submit(file=self.file('role.capk', self.capk())).status_code, 400)

    def test_capk_rejects_empty_entries_and_overlong_utf8_entry_names(self):
        header = b'KPAC'+struct.pack('<i', 1)+b'\x01x'+struct.pack('<i', 1)
        long_name = ('名'*100).encode('utf-8')
        invalid = [header+b'\x01f'+struct.pack('<i', 0),
                   header+b'\xac\x02'+long_name+struct.pack('<i', 1)+b'x']
        for body in invalid:
            with self.subTest(body=body[:20]):
                self.assertEqual(self.submit(file=self.file('role.capk', body), category='characters').status_code, 400)

    @override_settings(MAX_FILE_BYTES=10)
    def test_capk_size_limit_still_applies(self):
        response = self.submit(file=self.file('role.capk', self.capk()), category='characters')
        self.assertEqual(response.status_code, 413)

    @override_settings(MAX_FILE_BYTES=10)
    def test_oversized_file_rejected_without_orphans(self):
        self.assertEqual(self.submit(file=self.file('preset.txt', b'a' * 11)).status_code, 413)
        self.assertEqual(len(list(Path(self.temp.name).glob('*'))), 0)

    @override_settings(MAX_STORAGE_BYTES=10)
    def test_global_storage_limit_prevents_submission(self):
        self.assertEqual(self.submit().status_code, 507)
        self.assertEqual(len(list(Path(self.temp.name).glob('*'))), 0)

    def test_changed_metadata_waits_while_old_version_stays_public(self):
        item = self.created()
        revision = self.approve(item)
        response = self.client.post(f"/api/resources/{item['id']}/revisions/", {'title': '未审核新标题', 'description': '新介绍'})
        self.assertEqual(response.status_code, 201)
        public = self.reader.get(f"/api/resources/{item['id']}/").json()['data']
        self.assertEqual(public['title'], '投稿标题')
        self.assertEqual(public['file']['id'], revision)
        self.assertIsNone(public['latest_revision'])
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 1)

    def test_other_user_cannot_revise_or_view_private_submission(self):
        item = self.created()
        self.assertEqual(self.reader.post(f"/api/resources/{item['id']}/revisions/", {'title': '他人改动', 'description': 'bad'}).status_code, 404)
        self.assertEqual(self.reader.get(f"/api/resources/{item['id']}/?private=1").status_code, 404)

    def test_unpublished_resource_hidden_and_download_denied_to_reader(self):
        item = self.created()
        revision = self.approve(item)
        response = self.staff.post(f"/api/manage/resources/{item['id']}/", json.dumps({'action': 'unpublish', 'reason': '内容待核实'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reader.get(f"/api/resources/{item['id']}/").status_code, 404)
        self.assertEqual(self.reader.get(f'/download/{revision}/').status_code, 404)

    def test_double_review_is_conflict(self):
        item = self.created()
        revision = self.approve(item)
        response = self.staff.post(f'/api/manage/reviews/{revision}/', json.dumps({'action': 'reject', 'reason': '迟来的拒绝'}), content_type='application/json')
        self.assertEqual(response.status_code, 409)

    def test_raw_storage_urls_never_serve_private_files(self):
        item = self.created()
        for prefix in ('files', 'media', '_modshare_private'):
            self.assertEqual(self.reader.get(f"/{prefix}/{item['latest_revision']['id'].replace('-', '')}.blob").status_code, 404)

    def test_admin_can_page_through_every_submission_by_account(self):
        from community.models import Resource, Revision
        first = self.created()
        blob = Revision.objects.get(pk=first['latest_revision']['id']).blob
        added = [Resource(author=self.member, category='presets') for _ in range(200)]
        Resource.objects.bulk_create(added)
        Revision.objects.bulk_create([Revision(resource=r, blob=blob, title=f'投稿 {i}', description='介绍')
                                      for i, r in enumerate(added)])
        all_ids = set()
        for number in range(1, 10):
            data = self.staff.get(f'/api/manage/users/{self.member.id}/?page={number}').json()['data']
            self.assertEqual(data['resource_pagination']['total'], 201)
            self.assertEqual(data['resource_pagination']['pages'], 9)
            self.assertEqual(data['resource_pagination']['page'], number)
            all_ids.update(r['id'] for r in data['resources'])
        self.assertEqual(len(all_ids), 201)

    def test_post_commit_response_failure_preserves_committed_file(self):
        from community.models import Blob, Resource
        with patch('community.resources.resource_data', side_effect=OperationalError('injected response failure')):
            self.assertEqual(self.submit().status_code, 503)
        self.assertEqual(Resource.objects.count(), 1)
        blob = Blob.objects.get()
        self.assertTrue((Path(self.temp.name) / blob.storage_name).is_file())

    def test_post_commit_replacement_failure_preserves_both_files(self):
        from community.models import Blob
        item = self.created()
        with patch('community.resources.resource_data', side_effect=OperationalError('injected response failure')):
            response = self.client.post(f"/api/resources/{item['id']}/revisions/", {
                'title': '新版本', 'description': '新介绍', 'file': self.file('new.txt', b'new contents')})
            self.assertEqual(response.status_code, 503)
        self.assertEqual(Blob.objects.count(), 2)
        self.assertTrue(all((Path(self.temp.name) / b.storage_name).is_file() for b in Blob.objects.all()))
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 2)
