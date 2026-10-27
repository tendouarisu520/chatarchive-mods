from django.conf import settings
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.db import connection
from .common import success


def page(request, page='home', object_id=''):
    get_token(request)
    sitekey = settings.TURNSTILE_SITE_KEY if settings.TURNSTILE_ENABLED and page in ('login', 'register', 'reset') else ''
    return render(request, 'community/app.html', {'page': page, 'object_id': str(object_id),
        'app_base': settings.APP_BASE, 'turnstile_sitekey': sitekey})


def health(request):
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return success({'status': 'healthy'})
