"""Production settings.

Boots loudly or not at all: a misconfigured production deploy must fail on startup
rather than run insecurely (DEPLOYMENT.md §3).
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import ENCRYPTION_KEK, LOGGING, SECRET_KEY, env

DEBUG = False

_INSECURE_DEFAULTS = {
    "SECRET_KEY": (SECRET_KEY, "insecure-development-key-do-not-use"),
    "ENCRYPTION_KEK": (ENCRYPTION_KEK, ""),
}
for _name, (_value, _bad) in _INSECURE_DEFAULTS.items():
    if not _value or _value == _bad:
        raise ImproperlyConfigured(f"{_name} must be set to a real value in production.")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list explicit hosts in production.")

# --- transport security ---
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 60 * 60 * 8

# --- storage ---
if env("STORAGE_BACKEND", default="s3") == "s3":
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    AWS_STORAGE_BUCKET_NAME = env("STORAGE_BUCKET_PRIVATE")
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default=None)
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True  # signed URLs only
    AWS_QUERYSTRING_EXPIRE = env.int("SIGNED_URL_TTL_SECONDS", default=300)

# --- observability (Phase 10) ---
LOGGING["root"]["level"] = env("LOG_LEVEL", default="INFO")
# A log aggregator wants JSON; a human tailing production logs by eye can still ask for
# the plain formatter with an explicit override.
LOGGING["handlers"]["console"]["formatter"] = env("LOG_FORMAT", default="json")

if env("SENTRY_DSN", default=""):
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,
        environment=env("DJANGO_ENVIRONMENT", default="production"),
        # Set by CI to the deployed commit SHA/tag, if available — ties a Sentry issue to
        # exactly the build that produced it. Blank is fine; Sentry just omits the field.
        release=env("RELEASE_VERSION", default="") or None,
    )

# Row-Level Security is defence-in-depth (apps/core/migrations/0002_row_level_security.py)
# and stays inert until this is set — see that migration's docstring and
# `apps.core.tenant_session` for why a second, unprivileged role is required at all.
# Left unset here (not asserted like SECRET_KEY/ENCRYPTION_KEK above) because turning it
# on requires the `botbuilder_app` role to already exist, which the *first* deploy's
# migration run is what creates — asserting it non-empty would make that first deploy
# unable to boot. Set `DATABASE_APP_ROLE=botbuilder_app` from the second deploy onward.
