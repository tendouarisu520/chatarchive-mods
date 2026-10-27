import json
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = {}
if os.environ.get('MOD_CONFIG_FILE'):
    CONFIG = json.loads(Path(os.environ['MOD_CONFIG_FILE']).read_text(encoding='utf-8-sig'))
TURNSTILE = CONFIG.get('turnstile', {})
TURNSTILE_ENABLED = TURNSTILE.get('enabled', False) is True
TURNSTILE_SITE_KEY = TURNSTILE.get('site_key', '')
TURNSTILE_SECRET_KEY = TURNSTILE.get('secret_key', '')
TURNSTILE_HOSTNAMES = TURNSTILE.get('hostnames', [])
if TURNSTILE_ENABLED and (not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY
        or not isinstance(TURNSTILE_HOSTNAMES, list) or not TURNSTILE_HOSTNAMES
        or any(not isinstance(host, str) or not host for host in TURNSTILE_HOSTNAMES)):
    raise ImproperlyConfigured('Enabled Turnstile requires dedicated site/secret keys and explicit hostnames.')
DATA_DIR = Path(os.environ.get('MOD_DATA_DIR', BASE_DIR.parent / '.runtime' / 'modshare' / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY = CONFIG.get('secret_key', os.environ.get('MOD_SECRET_KEY', 'local-only-modshare-development-key'))
DEBUG = os.environ.get('MOD_DEBUG', '1' if not CONFIG else '0') == '1'
ALLOWED_HOSTS = CONFIG.get('allowed_hosts', ['127.0.0.1', 'localhost', 'testserver'])
APP_BASE = os.environ.get('MOD_SCRIPT_NAME', CONFIG.get('script_name', '')).rstrip('/')
FORCE_SCRIPT_NAME = APP_BASE or None
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
                  'django.contrib.messages', 'django.contrib.staticfiles', 'community.apps.CommunityConfig']
AUTH_USER_MODEL = 'community.User'
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_DIR / 'modshare.db',
                         'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'}}}
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
STATIC_URL = f'{APP_BASE}/static/'
STATIC_ROOT = DATA_DIR / 'static'
STATICFILES_DIRS = [BASE_DIR / 'static']
PRIVATE_ROOT = DATA_DIR / 'files'
PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
TEMP_ROOT = DATA_DIR / 'tmp'
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
FILE_UPLOAD_TEMP_DIR = str(TEMP_ROOT)
FILE_UPLOAD_MAX_MEMORY_SIZE = 262144
FILE_UPLOAD_HANDLERS = ['community.uploads.BoundedUploadHandler', 'django.core.files.uploadhandler.TemporaryFileUploadHandler']
DATA_UPLOAD_MAX_MEMORY_SIZE = 131072
DATA_UPLOAD_MAX_NUMBER_FIELDS = 15
DATA_UPLOAD_MAX_NUMBER_FILES = 2
MAX_FILE_BYTES = 50_000_000
MAX_PREVIEW_BYTES = 2_000_000
MAX_STORAGE_BYTES = int(os.environ.get('MOD_MAX_STORAGE_BYTES', '20000000000'))
DAILY_UPLOAD_LIMIT = 5
SESSION_COOKIE_NAME = 'modsessionid'
CSRF_COOKIE_NAME = 'modcsrftoken'
SESSION_COOKIE_PATH = CSRF_COOKIE_PATH = f'{APP_BASE}/'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = bool(CONFIG.get('secure', False))
SECURE_SSL_REDIRECT = bool(CONFIG.get('secure', False))
SECURE_HSTS_SECONDS = 31536000 if CONFIG.get('secure', False) else 0
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 7 * 86400
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
SMTP = CONFIG.get('smtp', {})
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend' if SMTP else 'django.core.mail.backends.locmem.EmailBackend'
EMAIL_HOST = SMTP.get('host', '')
EMAIL_PORT = int(SMTP.get('port', 465))
EMAIL_HOST_USER = SMTP.get('username', '')
EMAIL_HOST_PASSWORD = SMTP.get('password', '')
EMAIL_USE_SSL = SMTP.get('ssl', EMAIL_PORT == 465)
EMAIL_USE_TLS = not EMAIL_USE_SSL and EMAIL_PORT == 587
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = SMTP.get('from', 'ChatArchive 模组分享站 <noreply@localhost>')
X_ACCEL_DOWNLOADS = os.environ.get('MOD_X_ACCEL', '0') == '1'
CSRF_FAILURE_VIEW = 'community.common.csrf_failure'
MIDDLEWARE += ['community.common.ResponseHeadersMiddleware']
