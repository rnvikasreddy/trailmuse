"""TrailMuse settings. Everything environment-specific comes from environment variables (see .env.example)."""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "trails",
    "accounts",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "trails.context.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default="postgis://trailmuse:trailmuse@localhost:5432/trailmuse",
        conn_max_age=60,
    )
}
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Los_Angeles"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
# Serve uploaded photos from Django itself. Fine for a small site on one server with a
# persistent disk; switch off once photos move to object storage (S3, R2) behind a CDN.
SERVE_MEDIA = env_bool("SERVE_MEDIA", False)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "explore"
LOGOUT_REDIRECT_URL = "explore"

if not DEBUG:
    if SECRET_KEY.startswith("dev-only"):
        raise RuntimeError("Set SECRET_KEY when DEBUG is off.")
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- TrailMuse ---
# Map tiles. With a MapTiler key the app uses MapTiler's outdoor style; without one it
# falls back to OpenStreetMap's public raster tiles, which are fine for development only.
MAPTILER_KEY = os.environ.get("MAPTILER_KEY", "")
# Launch region, as west,south,east,north. Default: SF Bay Area.
REGION_BBOX = tuple(float(x) for x in os.environ.get("REGION_BBOX", "-123.1,36.95,-121.5,38.35").split(","))
REGION_NAME = os.environ.get("REGION_NAME", "the Bay Area")
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OPENTOPODATA_URL = os.environ.get("OPENTOPODATA_URL", "https://api.opentopodata.org/v1/srtm30m")
# Folder of SRTM .hgt tiles (e.g. N37W123.hgt). Used before the online elevation API when present.
ELEVATION_DIR = os.environ.get("ELEVATION_DIR", str(BASE_DIR / "data" / "srtm"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
