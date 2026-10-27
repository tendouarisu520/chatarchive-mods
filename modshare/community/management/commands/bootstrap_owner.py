import json
import os
import secrets
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from community.models import Audit, User


class Command(BaseCommand):
    help = 'Create the sole site owner and write credentials only to a protected file.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--credentials', required=True)

    def handle(self, *args, **options):
        email = options['email'].strip().casefold()
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError('Invalid owner email.')
        path = Path(options['credentials']).resolve()
        if path.is_symlink() or path.exists():
            raise CommandError('Credentials target must be a new protected file.')
        path.parent.mkdir(parents=True, exist_ok=True)
        password = secrets.token_urlsafe(27)
        written = False
        try:
            with transaction.atomic():
                if User.objects.filter(role='owner').exists():
                    raise CommandError('Owner already exists; use email password recovery. No changes made.')
                if User.objects.filter(email=email).exists():
                    raise CommandError('Owner email already registered; do not overwrite another account.')
                owner = User.objects.create_user(email=email, password=password, display_name='站主', role='owner')
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                written = True
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump({'email': email, 'password': password,
                               'url': settings.CONFIG.get('public_url', f'http://127.0.0.1:3310{settings.APP_BASE}/')}, output, ensure_ascii=False, indent=2)
                Audit.objects.create(actor=owner, action='bootstrap_owner', target=f'user:{owner.pk}')
        except BaseException:
            if written:
                path.unlink(missing_ok=True)
            raise
        self.stdout.write('Sole owner created. Credentials saved to the supplied protected file; no password logged.')
