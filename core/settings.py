"""Django settings for the Office Attendance System (ZKTeco F18 + RFID)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-this-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Vercel sets VERCEL=1 on every deployment.
ON_VERCEL = os.environ.get("VERCEL") == "1"

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]
if ON_VERCEL:
    ALLOWED_HOSTS += [".vercel.app", ".now.sh"]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_ORIGINS", "").split(",") if o
] + ["https://*.vercel.app"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.accounts",
    "apps.devices",
    "apps.attendance",
    "apps.leaves",
    "apps.tasks",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves CSS, the logo and the favicons straight from the app,
    # so no separate static host or CDN is needed.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.sidebar_badges",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# Local development falls back to SQLite. In production set DATABASE_URL
# (Vercel + Neon Postgres does this for you when you add the storage).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if DATABASE_URL:
    import dj_database_url

    DATABASES["default"] = dj_database_url.parse(
        DATABASE_URL,
        # Serverless functions are short-lived, so do not hold connections open.
        conn_max_age=0,
        ssl_require=True,
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
# Attendance is calculated in local naive time (in/out times, the 9 hour rule),
# so USE_TZ is deliberately set to False.
USE_TZ = False

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path("/tmp/staticfiles") if ON_VERCEL else BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
# WhiteNoise reads straight from STATICFILES_DIRS, so a deploy never depends on
# collectstatic having been run first.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

MEDIA_URL = "media/"
# Vercel's filesystem is read-only apart from /tmp, and /tmp is wiped between
# requests. Uploaded photos and attachments will therefore not survive on
# Vercel - move to S3 / Cloudinary / Vercel Blob when you need them to.
MEDIA_ROOT = Path("/tmp/media") if ON_VERCEL else BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "accounts:login"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ---- Security behind the Vercel proxy ----
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# ---- Branding (shown on the sidebar and the sign-in page) ----
SITE_NAME = "AttendTek"
SITE_TAGLINE = "Smart Biometric & RFID"   # leave blank to hide

# ---- Attendance business defaults (can be overridden per Shift) ----
DEFAULT_OFFICE_START = "09:00"
DEFAULT_OFFICE_END = "18:00"
DEFAULT_LATE_AFTER = "10:00"
DEFAULT_REQUIRED_HOURS = 9.0
