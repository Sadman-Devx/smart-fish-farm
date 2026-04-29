"""
Django settings for smart_fish_farm project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from celery.schedules import crontab
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# ── Security ───────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]


# ── Installed apps ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',

    # allauth
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',

    'rest_framework',
    'farm',
    'accounts',
]


# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.SessionActivityMiddleware',
]


ROOT_URLCONF = 'smart_fish_farm.urls'

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

WSGI_APPLICATION = 'smart_fish_farm.wsgi.application'


# ── Database ───────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "smart_fish_farm"),
        "USER": os.environ.get("DB_USER", "myuser"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}


# ── Auth ───────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'


# ── django-allauth ─────────────────────────────────────────────────────────────
SITE_ID = 2

# ── FIX: replaces deprecated ACCOUNT_EMAIL_REQUIRED + ACCOUNT_USERNAME_REQUIRED
# These two old settings caused the startup WARNING in the terminal.
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']

ACCOUNT_LOGIN_METHODS             = {'email'}
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# Keep legacy allauth compatibility as some environments still validate these.
ACCOUNT_AUTHENTICATION_METHOD     = 'email'
ACCOUNT_USERNAME_REQUIRED         = False
ACCOUNT_EMAIL_REQUIRED            = True
ACCOUNT_EMAIL_VERIFICATION        = 'optional'

ACCOUNT_LOGIN_URL                 = '/accounts/login/'
ACCOUNT_SIGNUP_URL                = '/accounts/register/'
SOCIALACCOUNT_LOGIN_CANCELLED_URL = '/accounts/login/'

SOCIALACCOUNT_AUTO_SIGNUP    = True
SOCIALACCOUNT_LOGIN_ON_GET   = True

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
    }
}


# ── Email ──────────────────────────────────────────────────────────────────────
EMAIL_BACKEND     = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST          = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT          = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS       = os.environ.get("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER     = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL  = os.environ.get("EMAIL_HOST_USER", "noreply@smartfishfarm.local")

FARM_NOTIFICATION_EMAIL = os.environ.get("FARM_NOTIFICATION_EMAIL", "farmer@example.com")


# ── Twilio SMS ─────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.environ.get("TWILIO_FROM_NUMBER", "")
TWILIO_TO_NUMBER    = os.environ.get("TWILIO_TO_NUMBER", "")


# ── Weather API ────────────────────────────────────────────────────────────────
WEATHER_API_KEY  = os.environ.get("OPENWEATHER_API_KEY", "")
WEATHER_LOCATION = os.environ.get("OPENWEATHER_LOCATION", "Chandpur,Bangladesh")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")


# ── Farm analytics defaults ────────────────────────────────────────────────────
FEED_COST_PER_KG        = float(os.environ.get("FEED_COST_PER_KG", "1.20"))
DEFAULT_FCR             = float(os.environ.get("DEFAULT_FCR", "1.50"))
DEFAULT_MARKET_WEIGHT_G = float(os.environ.get("DEFAULT_MARKET_WEIGHT_G", "500"))


# ── Celery ─────────────────────────────────────────────────────────────────────
#CELERY_BROKER_URL     = "memory://"
#CELERY_RESULT_BACKEND = "rpc://"
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

CELERY_TIMEZONE = 'Asia/Dhaka'
CELERY_ENABLE_UTC = False

CELERY_BEAT_SCHEDULE = {
    "daily-feed-alert-6am": {
        "task":     "farm.tasks.send_daily_feed_alert",
        "schedule": crontab(hour=6, minute=0),
    },
    "auto-log-water-temp-9am": {
        "task":     "farm.tasks.auto_log_water_temperature",
        "schedule": crontab(hour=9, minute=0),
    },
}


# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N      = True
USE_TZ        = True


# ── Static files ───────────────────────────────────────────────────────────────
STATIC_URL       = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'