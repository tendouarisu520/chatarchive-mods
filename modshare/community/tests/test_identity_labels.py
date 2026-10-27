from django.contrib.auth import get_user_model
from django.test import TestCase
from community.common import user_data
from . import test_resources


class IdentityLabelTests(TestCase):
    setUp=test_resources.ResourceTests.setUp
    tearDown=test_resources.ResourceTests.tearDown
    file=test_resources.ResourceTests.file
    submit=test_resources.ResourceTests.submit
    created=test_resources.ResourceTests.created
    approve=test_resources.ResourceTests.approve

    def test_role_label_keeps_original_nickname(self):
        owner=get_user_model().objects.create_user(email='owner-label@example.com',role='owner',display_name='三千年夜')
        for user,label in [(owner,'三千年夜（站长）'),(self.admin,'旅人（管理员）'),(self.member,'旅人')]:
            self.assertEqual(user_data(user)['display_label'],label)
            self.assertEqual(user_data(user)['display_name'],user.display_name)
        owner.refresh_from_db();self.assertEqual(owner.display_name,'三千年夜')

    def test_author_and_review_labels_follow_current_role(self):
        item=self.created();self.approve(item)
        path=f"/api/resources/{item['id']}/"
        self.assertEqual(self.reader.get(path).json()['data']['author']['name'],'旅人')
        self.member.role='admin';self.member.save(update_fields=['role'])
        self.assertEqual(self.reader.get(path).json()['data']['author']['name'],'旅人（管理员）')
        fresh=self.created()
        queue=self.staff.get('/api/manage/reviews/').json()['data']['items']
        entry=next(v for v in queue if v['resource_id']==fresh['id'])
        self.assertEqual(entry['author']['name'],'旅人（管理员）')
        self.member.role='user';self.member.save(update_fields=['role'])
        self.assertEqual(self.reader.get(path).json()['data']['author']['name'],'旅人')
