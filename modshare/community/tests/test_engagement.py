import json
from datetime import datetime, timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.utils import timezone
from . import test_resources


class EngagementTests(TestCase):
    def test_rating_thresholds_use_exact_ratio_not_rounded_display(self):
        from community.engagement import rating_summary
        for positive,negative,label in [(95,5,'好评如潮'),(949,51,'多半好评'),(70,30,'多半好评'),
            (699,301,'褒贬不一'),(40,60,'褒贬不一'),(399,601,'多半差评'),(20,80,'多半差评'),
            (199,801,'差评如潮'),(0,1,'差评如潮'),(1,0,'好评如潮'),(0,0,'暂无评价')]:
            summary=rating_summary(positive,negative)
            self.assertEqual(summary['label'],label)
            self.assertEqual(summary['total'],positive+negative)
        self.assertEqual(rating_summary(9499,501)['positive_percent'],94.9)
        self.assertTrue(rating_summary(1,0)['small_sample'])
        self.assertFalse(rating_summary(10,0)['small_sample'])

    setUp = test_resources.ResourceTests.setUp
    tearDown = test_resources.ResourceTests.tearDown
    file = test_resources.ResourceTests.file
    submit = test_resources.ResourceTests.submit
    created = test_resources.ResourceTests.created
    approve = test_resources.ResourceTests.approve

    def like(self, item, value=True, client=None):
        return (client or self.reader).post(f"/api/resources/{item['id']}/favorite/",
            json.dumps({'liked': value}), content_type='application/json')

    def rank(self, metric='downloads', period='all', **query):
        response = self.reader.get('/api/rankings/', {'metric': metric, 'period': period, **query})
        self.assertEqual(response.status_code, 200)
        return response.json()['data']

    def dislike(self,item,value=True,client=None):
        return (client or self.reader).post(f"/api/resources/{item['id']}/dislike/",
            json.dumps({'disliked':value}),content_type='application/json')

    def test_dislike_switches_mutually_and_cancellation_is_specific(self):
        item=self.created();self.approve(item)
        self.assertEqual(self.like(item).json()['data']['favorite_count'],1)
        for _ in range(2):
            response=self.dislike(item);self.assertEqual(response.status_code,200)
            data=response.json()['data']
            self.assertEqual((data['favorite_count'],data['dislike_count'],data['liked'],data['disliked']),(0,1,False,True))
        self.assertEqual(self.rank('likes')['total'],0)
        self.like(item,False)
        self.assertTrue(self.reader.get(f"/api/resources/{item['id']}/").json()['data']['disliked'])
        data=self.like(item).json()['data']
        self.assertEqual((data['favorite_count'],data['dislike_count'],data['liked'],data['disliked']),(1,0,True,False))
        self.dislike(item,False)
        self.assertTrue(self.reader.get(f"/api/resources/{item['id']}/").json()['data']['liked'])
        self.dislike(item);data=self.dislike(item,False).json()['data']
        self.assertEqual((data['favorite_count'],data['dislike_count'],data['liked'],data['disliked']),(0,0,False,False))

    def test_dislike_first_then_like_sets_first_positive_date_only_once(self):
        item=self.created();self.approve(item)
        with patch('community.engagement.timezone.now',return_value=timezone.now()-timedelta(days=60)):
            self.assertEqual(self.dislike(item).status_code,200)
        self.like(item)
        self.assertEqual(self.rank('likes','day')['items'][0]['score'],1)
        self.dislike(item)
        with patch('community.engagement.timezone.now',return_value=timezone.now()+timedelta(days=1)):
            self.like(item)
            self.assertEqual(self.rank('likes','day')['total'],0)

    def test_dislikes_follow_publication_and_ban_permissions(self):
        item=self.created()
        self.assertEqual(self.dislike(item).status_code,404)
        self.approve(item)
        self.assertEqual(self.dislike(item,client=Client()).status_code,401)
        self.assertEqual(self.dislike(item,'true').status_code,400)
        self.assertEqual(self.dislike(item).status_code,200)
        data=Client().get(f"/api/resources/{item['id']}/").json()['data']
        self.assertEqual(data['dislike_count'],1);self.assertFalse(data['disliked'])
        self.other.banned_at=timezone.now();self.other.save()
        self.assertEqual(self.dislike(item,False).status_code,403)
        self.assertEqual(Client().get(f"/api/resources/{item['id']}/").json()['data']['dislike_count'],0)
        self.staff.post(f"/api/manage/resources/{item['id']}/",json.dumps({'action':'unpublish','reason':'测试'}),content_type='application/json')
        self.assertEqual(self.dislike(item,client=self.client).status_code,404)

    def grab(self, revision, client=None, method='get', **headers):
        response = getattr(client or self.reader, method)(f'/download/{revision}/', **headers)
        response.close()
        return response.status_code

    def test_downloads_deduplicate_per_reader_and_day(self):
        item = self.created(); revision = self.approve(item)
        self.assertEqual(self.grab(revision), 200)
        self.assertEqual(self.grab(revision), 200)
        self.assertEqual(self.rank()['items'][0]['score'], 1)
        with patch('community.engagement.timezone.now', return_value=timezone.now()+timedelta(days=1)):
            self.assertEqual(self.grab(revision), 200)
        self.assertEqual(self.rank()['items'][0]['score'], 2)

    def test_private_head_range_failed_and_anonymous_downloads_do_not_count(self):
        item = self.created(); revision = item['latest_revision']['id']
        self.assertEqual(self.grab(revision, self.client), 200)
        self.approve(item)
        self.assertEqual(self.grab(revision, method='head'), 200)
        self.assertEqual(self.grab(revision, HTTP_RANGE='bytes=0-4'), 206)
        self.assertEqual(self.grab(revision, Client()), 401)
        self.assertEqual(self.grab(revision, HTTP_RANGE='bytes=90000-'), 416)
        self.assertEqual(self.rank()['total'], 0)

    def test_x_accel_downloads_count_full_get_only(self):
        item=self.created(); revision=self.approve(item)
        with self.settings(X_ACCEL_DOWNLOADS=True):
            self.assertEqual(self.grab(revision, method='head'), 200)
            self.assertEqual(self.grab(revision, HTTP_RANGE='bytes=0-4'), 200)
            self.assertEqual(self.rank()['total'], 0)
            self.assertEqual(self.grab(revision), 200)
        self.assertEqual(self.rank()['items'][0]['score'], 1)

    def test_review_route_excludes_current_published_version_and_checks_permission(self):
        item=self.created();revision=self.approve(item)
        route=f'/review-download/{revision}/'
        for viewer in [self.client,self.staff]:
            response=viewer.get(route)
            self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(self.rank()['total'],0)
        self.assertEqual(self.reader.get(route).status_code,404)
        self.assertEqual(self.grab(revision),200)
        self.assertEqual(self.rank()['items'][0]['score'],1)

    def test_favorite_is_idempotent_cancellable_and_relike_keeps_first_time(self):
        item=self.created(); self.approve(item)
        earlier=timezone.now()-timedelta(days=60)
        with patch('community.engagement.timezone.now', return_value=earlier):
            self.assertEqual(self.like(item).status_code, 200)
        self.assertEqual(self.like(item).json()['data']['favorite_count'], 1)
        self.assertEqual(self.rank('likes','day')['total'], 0)
        self.assertEqual(self.like(item,False).json()['data']['favorite_count'], 0)
        self.assertEqual(self.rank('likes')['total'], 0)
        self.assertEqual(self.like(item).status_code, 200)
        self.assertEqual(self.rank('likes','day')['total'], 0)
        self.assertEqual(self.rank('likes')['items'][0]['score'], 1)
        self.assertTrue(self.reader.get(f"/api/resources/{item['id']}/").json()['data']['liked'])
        self.assertFalse(Client().get(f"/api/resources/{item['id']}/").json()['data']['liked'])

    def test_pending_unpublished_banned_and_invalid_favorites_rejected(self):
        item=self.created()
        self.assertEqual(self.like(item).status_code,404)
        self.approve(item)
        self.assertEqual(self.like(item,'yes').status_code,400)
        self.assertEqual(self.like(item,client=Client()).status_code,401)
        self.like(item)
        self.grab(item['latest_revision']['id'])
        self.other.banned_at=timezone.now(); self.other.save()
        self.assertEqual(self.like(item,False).status_code,403)
        self.assertEqual(self.rank()['total'],0)
        self.assertEqual(self.rank('likes')['total'],0)
        self.other.banned_at=None; self.other.save()
        self.staff.post(f"/api/manage/resources/{item['id']}/",json.dumps({'action':'unpublish','reason':'测试'}),content_type='application/json')
        self.assertEqual(self.like(item).status_code,404)
        self.assertEqual(self.rank('likes')['total'],0)

    def test_period_boundaries_use_beijing_natural_calendar(self):
        from community.models import DownloadEvent
        item=self.created(); self.approve(item)
        now=timezone.make_aware(datetime(2026,10,6,0,1))
        for day in [now,now-timedelta(days=1),now-timedelta(days=5),now-timedelta(days=6),now-timedelta(days=36)]:
            with patch('community.engagement.timezone.now',return_value=day):
                self.grab(item['latest_revision']['id'])
        with patch('community.engagement.timezone.now',return_value=now):
            for period,expected in [('day',1),('week',2),('month',3),('all',5)]:
                self.assertEqual(self.rank(period=period)['items'][0]['score'],expected)
        self.assertEqual(DownloadEvent.objects.count(),5)

    def test_join_counts_do_not_multiply_and_category_filter_works(self):
        item=self.created(); self.approve(item)
        for who in [self.reader,self.client,self.staff]:
            self.like(item,client=who);self.grab(item['latest_revision']['id'],who)
        data=self.rank()['items'][0]
        self.assertEqual((data['score'],data['download_count'],data['favorite_count']),(3,3,3))
        self.assertEqual(self.rank('likes')['items'][0]['score'],3)
        self.assertEqual(self.rank(category='characters')['total'],0)
        self.assertEqual(self.rank(category='presets')['total'],1)

    def test_invalid_filters_and_empty_rankings(self):
        self.assertEqual(self.rank()['items'],[])
        for query in [{'metric':'bad'},{'period':'bad'},{'category':'bad'}]:
            self.assertEqual(self.reader.get('/api/rankings/',query).status_code,400)
        self.assertEqual(self.reader.get('/rankings/').status_code,200)

    def test_rank_pagination_has_stable_global_positions(self):
        from community.models import Resource,Revision,DownloadEvent
        first=self.created();self.approve(first)
        original=Revision.objects.get(pk=first['latest_revision']['id'])
        for index in range(25):
            resource=Resource.objects.create(author=self.member,category='presets',state='published',published_at=timezone.now())
            revision=Revision.objects.create(resource=resource,blob=original.blob,title=f'作品 {index}',description='分页测试',status='approved')
            resource.published_revision=revision;resource.save()
            DownloadEvent.objects.create(user=self.other,resource=resource,day=timezone.localdate())
        one=self.rank();two=self.rank(page=2)
        self.assertEqual(one['total'],25)
        self.assertEqual([r['rank'] for r in one['items']],list(range(1,25)))
        self.assertEqual(two['items'][0]['rank'],25)
        self.assertFalse(set(r['id'] for r in one['items'])&set(r['id'] for r in two['items']))

    def test_details_private_revision_and_moderation_permissions(self):
        item=self.created();self.approve(item)
        endpoint=f"/api/resources/{item['id']}/?private=1"
        self.assertEqual(self.reader.get(endpoint).status_code,404)
        self.assertEqual(self.staff.get(endpoint).status_code,200)
        action=f"/api/manage/resources/{item['id']}/"
        self.assertEqual(self.reader.post(action,json.dumps({'action':'unpublish','reason':'无权限'}),content_type='application/json').status_code,403)
        self.assertEqual(self.staff.post(action,json.dumps({'action':'unpublish','reason':'详情下架'}),content_type='application/json').status_code,200)
        self.assertEqual(self.staff.get(endpoint).json()['data']['status'],'unpublished')
        self.assertEqual(self.staff.post(action,json.dumps({'action':'restore'}),content_type='application/json').status_code,200)
