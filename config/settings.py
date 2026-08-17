"""
Django settings for the English Word Learning System.

See RD.md and AD.md for architecture decisions.

Environment variables:
    DJANGO_DEBUG          "true"/"1" → DEBUG=True (default: True; MUST be "false" in production)
    DJANGO_SECRET_KEY     REQUIRED in production; startup is refused without it
    DJANGO_ALLOWED_HOSTS  comma-separated list (default: "*")
    DJANGO_BEHIND_PROXY   "1" when gunicorn sits behind a TLS-terminating reverse
                          proxy (nginx/caddy); lets Django trust X-Forwarded-Proto
                          so Secure cookies and https redirects work
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in ("1", "true", "yes")


def _load_secret_key() -> str:
    """Production requires an explicit DJANGO_SECRET_KEY; refuse to start with
    the old hardcoded default (that string is public in Django docs/GitHub and
    would let anyone forge CSRF tokens / password-reset links).

    In dev (DEBUG=True) a fixed, clearly-marked dev key is used so sessions and
    CSRF tokens survive restarts. Never deploy with DEBUG=True.
    """
    key = os.environ.get("DJANGO_SECRET_KEY")
    if key:
        return key
    if not DEBUG:
        raise RuntimeError(
            "DJANGO_SECRET_KEY is not set. Refusing to start in production.\n"
            "Generate one with: python -c \"from django.core.management.utils "
            "import get_random_secret_key; print(get_random_secret_key())\""
        )
    return "dev-only-insecure-key-never-use-in-production"


SECRET_KEY = _load_secret_key()

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if h.strip()
]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "wordbank",
    "learning",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.version_info",
                "config.context_processors.accent_info",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database – SQLite with write-timeout for multi-worker deployments
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,  # seconds to wait for a write lock (D-10)
        },
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LOGIN_URL = "/account/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/account/login/"

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Session / CSRF security
# ---------------------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
# In production (DEBUG=False) the app is expected to sit behind TLS; cookies are
# marked Secure so they are never transmitted over plain HTTP. In dev
# (DEBUG=True, http://localhost) the Secure flag is off so local testing works.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# When running behind a TLS-terminating reverse proxy (nginx/caddy), Django must
# trust X-Forwarded-Proto to mark cookies Secure and emit https:// URLs.
# Enable ONLY when that proxy is actually in front (set DJANGO_BEHIND_PROXY=1);
# leaving it on without a proxy would let clients spoof the header.
if os.environ.get("DJANGO_BEHIND_PROXY") in ("1", "true", "yes"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# App logs go to a rotating file (local: logs/app.log, production: same path
# under /home/opc/bdc) plus stderr for dev. gunicorn --daemon discards worker
# stderr, so a file handler is required to actually inspect these logs in
# production. The "learning" logger runs at DEBUG so the recite drill's
# critical phases are traceable; django.security.csrf + django.request surface
# CSRF rejections and 4xx/5xx responses at a glance.
os.makedirs(BASE_DIR / "logs", exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stderr,
            "formatter": "verbose",
            "level": "DEBUG",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "app.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "verbose",
            "level": "DEBUG",
        },
    },
    "loggers": {
        "learning": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django.security.csrf": {
            "handlers": ["console", "file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
