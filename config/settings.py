"""
Django settings for the Shrive project.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-@5vqsamx&1#)ug@67(&c134t=z^pp*9@-qtin(tg=oh9*n5cej')
DEBUG = os.getenv('DJANGO_DEBUG', '1').strip().lower() in {'1', 'true', 'yes', 'on'}

def _parse_csv_env(value: str) -> list[str]:
    return [part.strip() for part in (value or '').split(',') if part.strip()]


def _normalise_host_token(token: str) -> str:
    value = (token or '').strip()
    if not value:
        return ''
    if value == '*':
        return '*'

    parsed = urlparse(value if '://' in value else f'//{value}')
    host = parsed.hostname or value
    host = host.strip()
    if host.startswith('*.'):
        host = '.' + host[2:]
    return host


default_allowed_hosts = ["127.0.0.1", "localhost"]
configured_allowed_hosts = [
    _normalise_host_token(host)
    for host in _parse_csv_env(os.getenv('DJANGO_ALLOWED_HOSTS', ''))
]
configured_allowed_hosts = [host for host in configured_allowed_hosts if host]
ALLOWED_HOSTS = configured_allowed_hosts or default_allowed_hosts
if DEBUG and not configured_allowed_hosts:
    ALLOWED_HOSTS = ["*"]

# CSRF_TRUSTED_ORIGINS for safe cross-origin requests (needed for Docker/proxy setups)
csrf_trusted_origins_raw = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
if csrf_trusted_origins_raw:
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_trusted_origins_raw.split(',') if origin.strip()]
else:
    # Auto-build from ALLOWED_HOSTS (common for Docker)
    CSRF_TRUSTED_ORIGINS = []
    for host in ALLOWED_HOSTS:
        if host != '*':
            csrf_host = f"*.{host[1:]}" if host.startswith('.') else host
            for scheme in ['http', 'https']:
                CSRF_TRUSTED_ORIGINS.append(f"{scheme}://{csrf_host}")

if os.getenv('DJANGO_TRUST_X_FORWARDED_PROTO', '1').strip().lower() in {'1', 'true', 'yes', 'on'}:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'drive.apps.DriveConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'drive.middleware.SystemTimezoneMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

APP_DATA_ROOT = Path(os.getenv('FILESHARE_DATA_ROOT', BASE_DIR)).expanduser()
APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)

FILESHARE_STORAGE_ROOT = APP_DATA_ROOT / 'storage'
FILESHARE_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': FILESHARE_STORAGE_ROOT / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-uk'
TIME_ZONE = 'Europe/London'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = APP_DATA_ROOT / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

LOGIN_URL = 'drive:login'
LOGIN_REDIRECT_URL = 'drive:space'
LOGOUT_REDIRECT_URL = 'drive:login'

DATA_UPLOAD_MAX_MEMORY_SIZE = None
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = None
DATA_UPLOAD_MAX_NUMBER_FILES = None
FILE_UPLOAD_TEMP_DIR = APP_DATA_ROOT / 'upload_tmp'
FILE_UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)

LOGS_DIR = APP_DATA_ROOT / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Configure extra read-only directories as dictionaries with name/path pairs.
# FILESHARE_READONLY_ROOTS = [
#     {'name': 'Server', 'path': '/'},
# ]

FILESHARE_DEFAULT_QUOTA_BYTES = 10 * 1024 * 1024 * 1024
FILESHARE_ENABLE_ADMIN_TODO = os.getenv('FILESHARE_ENABLE_ADMIN_TODO', '1').strip().lower() in {'1', 'true', 'yes', 'on'}
FILESHARE_ENABLE_EXPIRED_LINK_CLEANUP = True
FILESHARE_EXPIRED_LINK_CLEANUP_INTERVAL_SECONDS = 60

FILESHARE_TEXT_EDITOR_EXTENSIONS = [
    '.txt', '.md', '.csv', '.log', '.py', '.js', '.ts', '.tsx', '.jsx', '.json',
    '.html', '.css', '.scss', '.java', '.c', '.h', '.cpp', '.hpp', '.cs', '.go', '.rs', '.php',
    '.rb', '.sh', '.yml', '.yaml', '.xml', '.ini', '.cfg', '.conf', '.toml', '.sql', '.md', '.py',
]

DEFAULT_FROM_EMAIL = 'noreply@shrive.local'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'audit': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'audit_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'audit.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'audit',
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        'fileshare.audit': {
            'handlers': ['audit_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
