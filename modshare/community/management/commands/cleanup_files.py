from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from community.models import Blob, DailyUpload, StorageUsage, Throttle, EmailChallenge


class Command(BaseCommand):
    help = 'Remove stale orphan blobs and expired temporary/rate-limit records; preserve all referenced MOD files.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=1)
        removed = 0
        with transaction.atomic():
            known = set(Blob.objects.values_list('storage_name', flat=True))
            for candidate in settings.PRIVATE_ROOT.glob('*.blob'):
                if candidate.name not in known and candidate.stat().st_mtime < cutoff.timestamp():
                    candidate.resolve().relative_to(settings.PRIVATE_ROOT.resolve())
                    candidate.unlink()
                    removed += 1
        for candidate in settings.TEMP_ROOT.glob('*.upload*'):
            if candidate.stat().st_mtime < cutoff.timestamp():
                candidate.resolve().relative_to(settings.TEMP_ROOT.resolve())
                candidate.unlink()
                removed += 1
        EmailChallenge.objects.filter(expires_at__lt=cutoff).delete()
        Throttle.objects.filter(started_at__lt=timezone.now() - timedelta(days=2)).delete()
        DailyUpload.objects.filter(day__lt=timezone.localdate() - timedelta(days=90)).delete()
        self.stdout.write(f'Removed {removed} stale orphan/temp files; referenced resources retained.')
