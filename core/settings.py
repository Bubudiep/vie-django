from pathlib import Path
from dotenv import load_dotenv
from corsheaders.defaults import default_headers
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
SECRET_KEY = 'django-insecure-!q(0j9c_@%w20&dp3ji4n*y@mgk*r62_nqb!k!s2%6vo878d-k'
ZALO_APP_ID = os.getenv('ZALO_APP_ID', '')
# From the Zalo Mini App admin console — needed to exchange a member's
# getPhoneNumber() token for their real phone number server-side. Login
# falls back to accepting a raw `phone` in the request while DEBUG=True and
# this is unset, so local dev keeps working without it configured.
ZALO_APP_SECRET = os.getenv('ZALO_APP_SECRET', '')
# The club's own bank account, used to build a VietQR (img.vietqr.io) transfer
# QR for the "QR Thanh toán" button — VIETQR_BANK_ID is a bank BIN or VietQR
# short code (e.g. "970422" or "mbbank"), see https://vietqr.io for the list.
# Left empty until configured; the feature degrades to a friendly message.
VIETQR_BANK_ID = os.getenv('VIETQR_BANK_ID', '')
VIETQR_ACCOUNT_NO = os.getenv('VIETQR_ACCOUNT_NO', '')
VIETQR_ACCOUNT_NAME = os.getenv('VIETQR_ACCOUNT_NAME', '')
DEBUG = True
ALLOWED_HOSTS = ['itx.vba.io.vn','localhost','localhost:6001']
CSRF_TRUSTED_ORIGINS = [
    'https://itx.vba.io.vn',
    'http://itx.vba.io.vn',
]
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'channels',
    'chat',
    'store',
    'inventory',
    'membership',
    'rest_framework',
    'oauth2_provider',
    'accounts',
]

AUTH_USER_MODEL = 'accounts.User'
OAUTH2_PROVIDER_APPLICATION_MODEL = 'oauth2_provider.Application'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ALLOW_ALL_ORIGINS = False  # (dev local thôi)
CORS_ALLOWED_ORIGINS = [
    'http://localhost:6001',
    'http://localhost:3000',
    'http://localhost:3001',
    'http://localhost:3002',
    'http://localhost:3003',
    'https://itx.vba.io.vn',
    'http://itx.vba.io.vn',
    'https://h5.zdn.vn',
    'zbrowser://h5.zdn.vn',
]
CORS_ALLOW_HEADERS = (*default_headers, 'x-company-id')

ROOT_URLCONF = 'core.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 4},
    },
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Ho_Chi_Minh'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'oauth2_provider.contrib.rest_framework.OAuth2Authentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

AUTHENTICATION_BACKENDS = (
    'oauth2_provider.backends.OAuth2Backend',
    'accounts.backends.CompanyScopedBackend',
)

def _rotating_file_handler(name):
    return {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / f'{name}.log',
        'maxBytes': 5 * 1024 * 1024,
        'backupCount': 5,
        'formatter': 'verbose',
        # `runserver`'s autoreload watcher process also calls django.setup()
        # (hence configures this same LOGGING dict) but never actually emits
        # through it — with delay=False it would still open the file handle
        # up front, and on Windows that stray handle blocks the real worker
        # process's RotatingFileHandler from renaming the file on rollover
        # (os.rename fails while another process/handle has it open, unlike
        # POSIX). delay=True defers opening until the first real emit(), so
        # the watcher process never touches the file at all.
        'delay': True,
    }

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'django_file': _rotating_file_handler('django'),
        'accounts_file': _rotating_file_handler('accounts'),
        'chat_file': _rotating_file_handler('chat'),
        'store_file': _rotating_file_handler('store'),
        'inventory_file': _rotating_file_handler('inventory'),
        'membership_file': _rotating_file_handler('membership'),
        'oauth2_file': _rotating_file_handler('oauth2_provider'),
        'channels_server_file': _rotating_file_handler('channels_server'),
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'django_file'],
            'level': 'INFO',
            'propagate': False,
        },
        # Daphne's WebSocket connection log (HANDSHAKING/REJECT/DISCONNECT) —
        # split out from django.log so it doesn't drown out real request logs.
        'django.channels.server': {
            'handlers': ['console', 'channels_server_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console', 'accounts_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'chat': {
            'handlers': ['console', 'chat_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'store': {
            'handlers': ['console', 'store_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'inventory': {
            'handlers': ['console', 'inventory_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'membership': {
            'handlers': ['console', 'membership_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'oauth2_provider': {
            'handlers': ['console', 'oauth2_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}