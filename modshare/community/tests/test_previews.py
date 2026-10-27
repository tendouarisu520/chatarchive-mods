import io
import json
import struct
import zlib
from unittest.mock import patch
from PIL import Image, PngImagePlugin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from community.models import Blob, Revision, StorageUsage
from . import test_resources as existing_tests


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PreviewTests(TestCase):
    def test_card_evicted_between_stat_and_open_falls_back_to_source(self):
        from pathlib import Path
        from unittest.mock import patch
        item=self.created();self.approve(item);url=item['preview']['url']
        revision=Revision.objects.select_related('preview').get(pk=item['latest_revision']['id'])
        original=Path(self.temp.name)/revision.preview.storage_name
        content=original.read_bytes()
        card=Path(self.temp.name)/'evicted-card.webp';card.write_bytes(content)
        actual_open=Path.open
        def raced_open(path,*args,**kwargs):
            if path==card:raise FileNotFoundError('simulated cache pruning race')
            return actual_open(path,*args,**kwargs)
        self.reader.raise_request_exception=False
        with patch('community.previews.card_path',return_value=card),patch.object(Path,'open',new=raced_open):
            response=self.reader.get(url+'?size=card')
        self.assertEqual(response.status_code,200)
        self.assertEqual(b''.join(response.streaming_content),content);response.close()
        self.assertIn('full-v1',response['ETag'])

    def test_preview_revalidation_checks_current_permissions_before_304(self):
        item=self.created();self.approve(item);url=item['preview']['url']
        first=self.reader.get(url)
        first.close()
        self.assertEqual(first.status_code,200)
        self.assertIn('no-cache',first['Cache-Control'])
        self.assertIn('private',first['Cache-Control'])
        self.assertIn('Cookie',first['Vary'])
        etag=first['ETag']
        unchanged=self.reader.get(url,HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(unchanged.status_code,304)
        card=self.reader.get(url+'?size=card',HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(card.status_code,200);self.assertNotEqual(card['ETag'],etag);card.close()
        self.other.banned_at=timezone.now();self.other.save(update_fields=['banned_at'])
        self.assertEqual(self.reader.get(url,HTTP_IF_NONE_MATCH=etag).status_code,403)
        self.staff.post(f"/api/manage/resources/{item['id']}/",json.dumps({'action':'unpublish','reason':'测试'}),content_type='application/json')
        self.assertEqual(Client().get(url,HTTP_IF_NONE_MATCH=etag).status_code,404)

    def test_card_preview_is_small_and_uses_cached_derivative_after_authorization(self):
        import random
        from pathlib import Path
        output=io.BytesIO()
        # A reproducible detailed image reveals dimensions and transfer reduction.
        image=Image.frombytes('RGB',(1400,1000),random.Random(7).randbytes(1400*1000*3))
        image.save(output,format='WEBP',quality=75);image.close()
        response=self.submit(SimpleUploadedFile('large.webp',output.getvalue()))
        self.assertEqual(response.status_code,201,response.content)
        item=response.json()['data'];self.approve(item)
        with self.settings(TEMP_ROOT=Path(self.temp.name)/'cache'):
            url=item['preview']['url']+'?size=card'
            response=Client().get(url);data=b''.join(response.streaming_content);response.close()
            with Image.open(io.BytesIO(data)) as card:self.assertLessEqual(max(card.size),640)
            self.assertLess(len(data),item['preview']['size']//2)
            public=self.reader.get(f"/api/resources/{item['id']}/").json()['data']
            self.assertEqual(public['preview']['thumbnail_url'],url)
            from community import previews
            with patch.object(previews.Image,'open',side_effect=AssertionError('cache must skip decode')):
                self.assertEqual(self.picture_status(Client(),url),200)
            head=Client().head(url);self.assertEqual(int(head['Content-Length']),len(data))
            self.member.banned_at=timezone.now();self.member.save()
            self.assertEqual(self.picture_status(self.client,url),403)
            self.staff.post(f"/api/manage/resources/{item['id']}/",json.dumps({'action':'unpublish','reason':'测试'}),content_type='application/json')
            self.assertEqual(self.picture_status(Client(),url),404)
            self.assertEqual(self.picture_status(self.staff,url),200)

    def test_thumbnail_storage_failure_falls_back_and_unknown_size_rejected(self):
        item=self.created();self.approve(item);url=item['preview']['url']
        self.assertEqual(self.picture_status(Client(),url+'?size=unknown'),400)
        from community import previews
        with patch.object(previews,'card_path',side_effect=OSError('disk error')):
            self.assertEqual(self.picture_status(Client(),url+'?size=card'),200)

    def test_thumbnail_cache_prunes_older_files_and_keeps_source_and_quota(self):
        from pathlib import Path
        from community import previews
        item=self.created();revision=Revision.objects.select_related('preview').get(pk=item['latest_revision']['id'])
        before=StorageUsage.objects.get(pk=1).bytes
        original=Path(self.temp.name)/revision.preview.storage_name
        with self.settings(TEMP_ROOT=Path(self.temp.name)/'cache'):
            directory=Path(self.temp.name)/'cache'/'preview-cards';directory.mkdir(parents=True)
            stale=directory/'older.webp';stale.write_bytes(b'x'*2048)
            with patch.object(previews,'MAX_CARD_CACHE_BYTES',1024):
                target=previews.card_path(original,revision.preview)
            self.assertTrue(target.is_file());self.assertFalse(stale.exists())
            self.assertTrue(original.is_file());self.assertEqual(StorageUsage.objects.get(pk=1).bytes,before)
            self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'],1)
    def test_same_timestamp_revisions_still_follow_submission_order(self):
        import uuid
        manager=Revision.objects
        original_create=manager.create
        identifiers=iter([300,200,100])
        def decreasing_id(**kwargs):
            return original_create(id=uuid.UUID(int=next(identifiers)),**kwargs)
        with patch('community.resources.timezone.now',return_value=timezone.now()),patch.object(manager,'create',side_effect=decreasing_id):
            item=self.created()
            changed=self.revise(item).json()['data']
            self.assertEqual(changed['latest_revision']['id'],str(uuid.UUID(int=200)))
            removed=self.revise(item,remove_preview='1').json()['data']
            self.assertEqual(removed['latest_revision']['id'],str(uuid.UUID(int=100)))
            self.assertIsNone(removed['preview'])
    setUp = existing_tests.ResourceTests.setUp
    tearDown = existing_tests.ResourceTests.tearDown
    file = existing_tests.ResourceTests.file
    approve = existing_tests.ResourceTests.approve

    def picture_status(self, client, url, **kwargs):
        response = client.get(url, **kwargs)
        status = response.status_code
        response.close()
        return status

    def image(self, format='PNG', color='blue', padding=0):
        output = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Comment', 'private generation metadata')
        Image.new('RGB', (96, 64), color).save(output, format=format,
                                             **({'pnginfo': metadata} if format == 'PNG' else {}))
        suffix = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[format]
        return SimpleUploadedFile('example.' + suffix, output.getvalue() + b'\0' * padding)

    def archive(self):
        import zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('character.json', '{"name":"test"}')
        return self.file('character.zip', output.getvalue())

    def submit(self, preview=None, category='characters'):
        body = {'category': category, 'title': '角色例图测试', 'description': '介绍',
                'file': self.archive() if category == 'characters' else self.file()}
        if preview is not None:
            body['preview'] = preview
        return self.client.post('/api/uploads/', body)

    def created(self):
        response = self.submit(self.image())
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['data']

    def revise(self, item, **extra):
        return self.client.post(f"/api/resources/{item['id']}/revisions/",
                                {'title': '新修订', 'description': '新介绍', **extra})

    def test_pending_preview_private_then_published_inline_and_metadata_removed(self):
        item = self.created()
        url = item['preview']['url']
        self.assertEqual(self.picture_status(Client(), url), 404)
        self.assertEqual(self.picture_status(self.reader, url), 404)
        self.assertEqual(self.picture_status(self.staff, url), 200)
        response = self.client.get(url)
        self.assertEqual(response['Content-Type'], 'image/webp')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('inline', response['Content-Disposition'])
        data = b''.join(response.streaming_content)
        response.close()
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.format, 'WEBP')
        self.assertNotIn('Comment', image.info)
        self.assertNotIn(b'private generation metadata', data)
        queue = self.staff.get('/api/manage/reviews/').json()['data']['items'][0]
        self.assertEqual(queue['preview']['url'], url)
        self.approve(item)
        self.assertEqual(self.picture_status(Client(), url), 200)
        head = Client().head(url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(int(head['Content-Length']), len(data))
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 1)
        self.assertEqual(StorageUsage.objects.get(pk=1).bytes, sum(Blob.objects.values_list('size', flat=True)))

    def test_new_preview_waits_for_review_and_old_url_becomes_private_after_approval(self):
        item = self.created()
        self.approve(item)
        old_url = item['preview']['url']
        response = self.revise(item, preview=self.image(color='red'))
        self.assertEqual(response.status_code, 201)
        changed = response.json()['data']
        new_url = changed['preview']['url']
        self.assertNotEqual(old_url, new_url)
        public = self.reader.get(f"/api/resources/{item['id']}/").json()['data']
        self.assertEqual(public['preview']['url'], old_url)
        self.assertEqual(self.picture_status(Client(), old_url), 200)
        self.assertEqual(self.picture_status(Client(), new_url), 404)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 2)
        self.approve(changed)
        self.assertEqual(self.picture_status(Client(), old_url), 404)
        self.assertEqual(self.picture_status(Client(), new_url), 200)

    def test_text_revision_preserves_picture_and_delete_waits_for_review(self):
        item = self.created()
        first = Revision.objects.get(pk=item['latest_revision']['id'])
        self.approve(item)
        changed = self.revise(item).json()['data']
        self.assertEqual(Revision.objects.get(pk=changed['latest_revision']['id']).preview_id, first.preview_id)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 1)
        removed = self.revise(item, remove_preview='1').json()['data']
        self.assertIsNone(removed['preview'])
        self.assertEqual(self.picture_status(Client(), item['preview']['url']), 200)
        self.approve(removed)
        self.assertIsNone(self.reader.get(f"/api/resources/{item['id']}/").json()['data']['preview'])
        self.assertEqual(self.picture_status(Client(), item['preview']['url']), 404)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 1)

    def test_ban_and_unpublish_revoke_picture_even_for_existing_sessions(self):
        item = self.created()
        self.approve(item)
        url = item['preview']['url']
        self.member.banned_at = timezone.now()
        self.member.save(update_fields=['banned_at'])
        self.assertEqual(self.picture_status(self.client, url), 403)
        self.assertEqual(self.picture_status(self.client, url, HTTP_RANGE='bytes=0-9'), 403)
        self.staff.post(f"/api/manage/resources/{item['id']}/", json.dumps({'action': 'unpublish', 'reason': '测试'}), content_type='application/json')
        self.assertEqual(self.picture_status(Client(), url), 404)
        self.assertEqual(self.picture_status(self.staff, url), 200)

    def test_oversized_preview_rejected_without_blob_or_quota(self):
        response = self.submit(self.image(padding=2_000_001))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['error']['code'], 'preview_too_large')
        self.assertEqual(Blob.objects.count(), 0)
        self.assertEqual(list(self.temp_path().iterdir()), [])
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 0)

    def temp_path(self):
        from pathlib import Path
        return Path(self.temp.name)

    def test_exact_two_million_bytes_accepted(self):
        image = self.image()
        content = image.read()
        preview = SimpleUploadedFile('boundary.png', content + b'\0' * (2_000_000 - len(content)))
        self.assertEqual(self.submit(preview).status_code, 201)

    def test_formats_supported_and_fake_svg_gif_mismatches_rejected(self):
        for format in ('PNG', 'JPEG', 'WEBP'):
            self.assertEqual(self.submit(self.image(format=format)).status_code, 201)
        for preview in (SimpleUploadedFile('fake.png', b'<svg onload="alert(1)"/>'),
                        SimpleUploadedFile('image.svg', b'<svg/>'),
                        SimpleUploadedFile('wrong.jpg', self.image().read()),
                        SimpleUploadedFile('empty.png', b'')):
            self.assertEqual(self.submit(preview).status_code, 400)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'], 3)

    def test_preset_preview_published_and_duplicate_preview_fields_rejected(self):
        response=self.submit(self.image(),category='presets')
        self.assertEqual(response.status_code,201,response.content)
        item=response.json()['data'];url=item['preview']['url']
        self.assertEqual(self.picture_status(Client(),url),404)
        self.assertEqual(self.picture_status(self.staff,url),200)
        self.approve(item)
        self.assertEqual(self.picture_status(Client(),url),200)
        self.assertEqual(self.reader.get('/api/resources/?category=presets').json()['data']['items'][0]['preview']['url'],url)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'],1)
        before=Blob.objects.count()
        self.assertEqual(self.submit([self.image(), self.image()]).status_code, 400)
        self.assertEqual(Blob.objects.count(),before)

    def test_preset_preview_replace_and_remove_wait_for_review(self):
        item=self.submit(self.image(),category='presets').json()['data'];self.approve(item)
        old=item['preview']['url']
        response=self.revise(item,preview=self.image(color='red'));self.assertEqual(response.status_code,201)
        changed=response.json()['data'];new=changed['preview']['url']
        self.assertEqual(self.picture_status(Client(),old),200);self.assertEqual(self.picture_status(Client(),new),404)
        self.approve(changed)
        self.assertEqual(self.picture_status(Client(),new),200);self.assertEqual(self.picture_status(Client(),old),404)
        removed=self.revise(item,remove_preview='1').json()['data'];self.assertIsNone(removed['preview'])
        self.assertEqual(self.picture_status(Client(),new),200)
        self.approve(removed);self.assertEqual(self.picture_status(Client(),new),404)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'],2)

    def test_preset_invalid_and_oversized_preview_do_not_consume_quota(self):
        self.assertEqual(self.submit(self.image(padding=2_000_001),category='presets').status_code,413)
        self.assertEqual(self.submit(SimpleUploadedFile('fake.png',b'not an image'),category='presets').status_code,400)
        self.assertEqual(Blob.objects.count(),0)
        self.assertEqual(self.client.get('/api/me/').json()['data']['quota']['used'],0)

    def test_animated_webp_rejected(self):
        output = io.BytesIO()
        Image.new('RGB', (10, 10), 'red').save(output, format='WEBP', save_all=True,
                                             append_images=[Image.new('RGB', (10, 10), 'blue')], duration=100)
        self.assertEqual(self.submit(SimpleUploadedFile('animated.webp', output.getvalue())).status_code, 400)

    def test_pixel_bomb_rejected_before_decode(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 4001, 4000, 8, 2, 0, 0, 0)) + chunk(b'IDAT', b'')
        response = self.submit(SimpleUploadedFile('huge.png', data))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'preview_dimensions')

    def test_preview_revisions_cannot_evade_daily_limit(self):
        item = self.created()
        for _ in range(4):
            self.assertEqual(self.revise(item, preview=self.image()).status_code, 201)
        before = Blob.objects.count()
        self.assertEqual(self.revise(item, preview=self.image()).status_code, 429)
        self.assertEqual(Blob.objects.count(), before)
        self.assertEqual(len(list(self.temp_path().glob('*.blob'))), before)

    @override_settings(MAX_STORAGE_BYTES=1)
    def test_storage_failure_cleans_archive_and_picture(self):
        self.assertEqual(self.submit(self.image()).status_code, 507)
        self.assertEqual(list(self.temp_path().iterdir()), [])
        self.assertEqual(Blob.objects.count(), 0)

    def test_database_failure_cleans_both_prepared_files(self):
        with patch('community.resources.Revision.objects.create', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                self.submit(self.image())
        self.assertEqual(list(self.temp_path().iterdir()), [])
        self.assertEqual(Blob.objects.count(), 0)

    def test_cannot_upload_and_remove_picture_together(self):
        item = self.created()
        self.assertEqual(self.revise(item, preview=self.image(), remove_preview='1').status_code, 400)
