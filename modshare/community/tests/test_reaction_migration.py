from datetime import timedelta
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class ReactionMigrationTests(TransactionTestCase):
    old=('community','0004_downloadevent_favorite')
    latest=('community','0005_remove_favorite_community_f_resourc_d587ee_idx_and_more')

    def tearDown(self):
        MigrationExecutor(connection).migrate([self.latest])
        super().tearDown()

    def test_existing_active_and_cancelled_favorites_keep_dates_and_exclusive_constraint(self):
        executor=MigrationExecutor(connection);executor.migrate([self.old])
        apps=executor.loader.project_state([self.old]).apps
        User=apps.get_model('community','User');Resource=apps.get_model('community','Resource');Favorite=apps.get_model('community','Favorite')
        author=User.objects.create(username='legacy-author',email='legacy-author@example.com')
        reader=User.objects.create(username='legacy-reader',email='legacy-reader@example.com')
        resource=Resource.objects.create(author=author,category='presets')
        date=timezone.now()-timedelta(days=65)
        first=Favorite.objects.create(user=author,resource=resource,active=True,created_at=date)
        second=Favorite.objects.create(user=reader,resource=resource,active=False,created_at=date)
        executor=MigrationExecutor(connection);executor.migrate([self.latest])
        Favorite=executor.loader.project_state([self.latest]).apps.get_model('community','Favorite')
        for pk,active in [(first.pk,True),(second.pk,False)]:
            entry=Favorite.objects.get(pk=pk)
            self.assertEqual(entry.first_liked_at,date)
            self.assertEqual(entry.created_at,date)
            self.assertEqual(entry.active,active)
            self.assertFalse(entry.disliked)
        with self.assertRaises(IntegrityError),transaction.atomic():
            Favorite.objects.filter(pk=first.pk).update(active=True,disliked=True)
