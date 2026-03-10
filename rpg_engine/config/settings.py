import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() == 'true'
_env_hosts = [h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]
ALLOWED_HOSTS = sorted(set(_env_hosts + ['127.0.0.1', 'localhost', '0.0.0.0', 'testserver']))

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'game',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
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

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///db.sqlite3')
_db_conn_max_age = int(os.getenv('DB_CONN_MAX_AGE', '600'))
try:
    _default_db = dj_database_url.parse(DATABASE_URL, conn_max_age=_db_conn_max_age)
except TypeError:
    _default_db = dj_database_url.parse(DATABASE_URL)
    _default_db['CONN_MAX_AGE'] = _db_conn_max_age

DATABASES = {
    'default': _default_db
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = os.getenv('DJANGO_TIME_ZONE', 'America/New_York')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ]
}

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
RPG_OUTPUT_LANGUAGE = os.getenv('RPG_OUTPUT_LANGUAGE', 'English')
TRADE_TAX_RATE = os.getenv('TRADE_TAX_RATE', '0.05')
MONGODB_URI = os.getenv('MONGODB_URI', '')
MONGODB_DB_NAME = os.getenv('MONGODB_DB_NAME', 'rpg_game')
