"""Test settings: fast, hermetic, no external services."""

from .base import *  # noqa: F403
from .base import BASE_DIR, DATABASES, REST_FRAMEWORK, env

DEBUG = False
ALLOWED_HOSTS = ["*"]

# CI and local runs point at a throwaway PostgreSQL. Keep the engine identical to
# production — a test suite on a different database proves less than it appears to.
if env("TEST_DATABASE_URL", default=""):
    DATABASES = {"default": env.db("TEST_DATABASE_URL")}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Plain static storage: the manifest backend requires `collectstatic` to have run, and
# without it every admin template render raises. Production keeps the hashed manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

ENCRYPTION_KEK = "dGVzdC1vbmx5LWtleS0zMi1ieXRlcy1sb25nISEhISE="  # 32 bytes, test only
ENCRYPTION_KEK_VERSION = 1
ENCRYPTION_KEK_PREVIOUS = ""

MEDIA_ROOT = BASE_DIR / "test-media"

# Throttling off by default so tests assert behaviour, not rate limits. Rates must
# be None as well: views that opt into ScopedRateThrottle explicitly would otherwise
# still throttle, and a shared local-memory cache carries counts between tests.
# tests/test_throttling.py re-enables it deliberately.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": (),
    "DEFAULT_THROTTLE_RATES": {key: None for key in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]},
}
