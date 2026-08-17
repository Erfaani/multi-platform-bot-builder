"""Base settings shared by every environment.

Environment-specific modules (local / production / test) import from here and override.
Nothing secret is ever defaulted to a usable value; production asserts on boot.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BASE_DIR.parent

env = environ.Env()
env.read_env(str(ROOT_DIR / ".env"))

# --------------------------------------------------------------------------- core
SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-development-key-do-not-use")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ENVIRONMENT = env("DJANGO_ENVIRONMENT", default="local")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

BACKEND_BASE_URL = env("BACKEND_BASE_URL", default="http://localhost:8000")
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:3000")
PUBLIC_WEBHOOK_BASE_URL = env("PUBLIC_WEBHOOK_BASE_URL", default=BACKEND_BASE_URL)

# --------------------------------------------------------------------------- apps
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "django_prometheus",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

# See PHASES.md. Apps appear here as their phase lands; several are registered
# manifest-only in Phase 2 (they declare sellable features but have no models yet)
# and gain models and handlers in Phase 7.
LOCAL_APPS = [
    # Phase 1 — foundation
    "apps.core",
    "apps.accounts",
    "apps.customers",
    "apps.audit",
    "apps.i18n_content",
    # Phase 2 — catalogue, pricing, builder, preview
    "apps.platforms",
    "apps.features",
    "apps.business_templates",
    "apps.pricing",
    "apps.orders",
    # Phase 3 — orders, manual payments, notifications
    "apps.payments",
    "apps.notifications",
    # Phase 4 — bots, provisioning, runtime
    "apps.bots",
    "apps.provisioning",
    "apps.bot_runtime",
    "apps.businesses",
    # Phase 6 — customer dashboard
    "apps.analytics",
    "apps.support",
    # Phase 7 — business modules
    "apps.appointments",
    "apps.commerce",
    "apps.crm",
    # Phase 8 — AI assistant
    "apps.ai",
    # Phase 9 — subscriptions
    "apps.subscriptions",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# --------------------------------------------------------------------------- middleware
MIDDLEWARE = [
    # Must be first, per django-prometheus: it starts the request timer before anything
    # else runs, so `PrometheusAfterMiddleware` (must be last) reports the full latency.
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.LocaleResolutionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.MaintenanceModeMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
            ],
        },
    },
]

# --------------------------------------------------------------------------- database
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://botbuilder:botbuilder@localhost:5432/botbuilder",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["ATOMIC_REQUESTS"] = False  # transactions belong to the service layer

#: The unprivileged role every connection `SET ROLE`s into (`apps.core.tenant_session`)
#: so the PostgreSQL Row-Level Security policies from `apps.core`'s
#: `0002_row_level_security` migration actually apply — RLS is bypassed unconditionally
#: for a superuser or a table's own owner, which is what `DATABASE_URL` connects as by
#: default (it's also the role that ran the migrations). Empty by default (local/test):
#: RLS policies still exist, but the app keeps its owner privileges and nothing is
#: enforced — set this once a deployment is ready to actually drop privileges.
DATABASE_APP_ROLE = env("DATABASE_APP_ROLE", default="")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --------------------------------------------------------------------------- cache / celery
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://localhost:6379/3"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TIMEZONE = "UTC"

# The `beat` service (docker-compose.yml) reads this. Kept as a plain settings dict
# rather than `django_celery_beat`'s DB-backed schedule — nothing here needs to change
# without a deploy, and a static schedule is one less moving part to get wrong.
#
# Phase 10 audit: `sweep-outbox` through `purge-sessions` below are safety-net/DLQ tasks
# that already existed in code — each one's own docstring describes it as a periodic
# sweep — but were never actually entered here, so none of them had ever run outside a
# test or a manual shell call. `outbound-retry` is the sharpest gap: it is the *only*
# thing that ever re-attempts a rate-limited outbound message, so until this was added,
# a message deferred by rate limiting stayed QUEUED forever in any real deployment.
CELERY_BEAT_SCHEDULE = {
    "appointment-reminders": {
        "task": "apps.appointments.tasks.send_due_reminders",
        "schedule": 300.0,  # apps/appointments/tasks.py:SWEEP_INTERVAL_SECONDS
    },
    "subscription-sweep": {
        "task": "apps.subscriptions.tasks.sweep_subscriptions",
        "schedule": 3600.0,  # apps/subscriptions/tasks.py:SWEEP_INTERVAL_SECONDS
    },
    "sweep-outbox": {
        "task": "apps.core.tasks.sweep_pending_outbox",
        "schedule": 300.0,  # apps/core/tasks.py:SWEEP_INTERVAL_SECONDS
    },
    "purge-idempotency-records": {
        "task": "apps.core.tasks.purge_expired_idempotency_records",
        "schedule": 21600.0,  # apps/core/tasks.py:PURGE_INTERVAL_SECONDS
    },
    "check-bot-pool-depth": {
        "task": "apps.provisioning.tasks.check_pool_depth",
        "schedule": 1800.0,  # apps/provisioning/tasks.py:CHECK_POOL_DEPTH_INTERVAL_SECONDS
    },
    "sweep-inbound-updates": {
        "task": "apps.bot_runtime.tasks.sweep_pending_updates",
        "schedule": 120.0,  # apps/bot_runtime/tasks.py:SWEEP_INTERVAL_SECONDS
    },
    "outbound-retry": {
        "task": "apps.bot_runtime.tasks.retry_outbound",
        "schedule": 60.0,  # apps/bot_runtime/tasks.py:RETRY_OUTBOUND_INTERVAL_SECONDS
    },
    "purge-sessions": {
        "task": "apps.bot_runtime.tasks.purge_expired_sessions",
        "schedule": 21600.0,  # apps/bot_runtime/tasks.py:PURGE_SESSIONS_INTERVAL_SECONDS
    },
}

# --------------------------------------------------------------------------- auth
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2id first; see SECURITY.md §2.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------- DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # Applies the authenticated user's locale; see the module docstring.
        "apps.accounts.authentication.LocaleAwareJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "apps.core.exception_handler.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": f"{env.int('THROTTLE_ANON_PER_MIN', default=60)}/min",
        "user": f"{env.int('THROTTLE_USER_PER_MIN', default=600)}/min",
        "auth": f"{env.int('THROTTLE_AUTH_PER_MIN', default=10)}/min",
        "upload": f"{env.int('THROTTLE_UPLOAD_PER_HOUR', default=20)}/hour",
    },
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_LIFETIME_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_LIFETIME_DAYS", default=14)),
    "ROTATE_REFRESH_TOKENS": env.bool("JWT_ROTATE_REFRESH_TOKENS", default=True),
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Bot Builder Platform API",
    "DESCRIPTION": "Multi-tenant Bot-as-a-Service platform for Telegram and Bale.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
}

# --------------------------------------------------------------------------- CORS
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (
    "accept",
    "accept-language",
    "authorization",
    "content-type",
    "idempotency-key",
    "x-tenant",
    "x-request-id",
    "x-quote-session",
)
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:3000"])

# --------------------------------------------------------------------------- i18n
LANGUAGE_CODE = env("DEFAULT_LOCALE", default="en")
ACTIVE_LOCALES = env.list("ACTIVE_LOCALES", default=["en", "fa"])
LANGUAGES = [("en", "English"), ("fa", "فارسی")]
RTL_LANGUAGES = {"fa", "ar", "he", "ur"}
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
USE_L10N = True
USE_TZ = True
TIME_ZONE = env("DEFAULT_TIMEZONE", default="UTC")

DEFAULT_CURRENCY = env("DEFAULT_CURRENCY", default="USD")
ACTIVE_CURRENCIES = env.list("ACTIVE_CURRENCIES", default=["USD", "EUR", "IRR", "USDT"])

# --------------------------------------------------------------------------- static / media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# User uploads are NEVER served publicly; see SECURITY.md §7.
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = None

SIGNED_URL_TTL_SECONDS = env.int("SIGNED_URL_TTL_SECONDS", default=300)

# --------------------------------------------------------------------------- encryption
ENCRYPTION_KEK = env("ENCRYPTION_KEK", default="")
ENCRYPTION_KEK_VERSION = env.int("ENCRYPTION_KEK_VERSION", default=1)
ENCRYPTION_KEK_PREVIOUS = env("ENCRYPTION_KEK_PREVIOUS", default="")

# --------------------------------------------------------------------------- email
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@example.com")

# --------------------------------------------------------------------------- platforms
# Per-platform egress. Telegram is typically unreachable from Iranian infrastructure and
# Bale is best reached from inside it, so base URL, proxy and timeouts are configuration
# rather than constants — the two workers can run in different regions unchanged.
# See docs/00-ANALYSIS.md R-03.
PLATFORM_EGRESS = {
    "telegram": {
        "base_url": env("TELEGRAM_API_BASE_URL", default="https://api.telegram.org"),
        "proxy": env("TELEGRAM_PROXY_URL", default=""),
        "timeout_seconds": env.float("TELEGRAM_TIMEOUT_SECONDS", default=20.0),
    },
    "bale": {
        "base_url": env("BALE_API_BASE_URL", default="https://tapi.bale.ai"),
        "proxy": env("BALE_PROXY_URL", default=""),
        "timeout_seconds": env.float("BALE_TIMEOUT_SECONDS", default=20.0),
    },
}

#: Telegram's documented limits, applied before we get throttled rather than after.
OUTBOUND_RATE_PER_BOT_PER_SECOND = env.int("OUTBOUND_RATE_PER_BOT_PER_SECOND", default=30)
OUTBOUND_RATE_PER_CHAT_PER_SECOND = env.int("OUTBOUND_RATE_PER_CHAT_PER_SECOND", default=1)

SESSION_IDLE_TIMEOUT_SECONDS = env.int("SESSION_IDLE_TIMEOUT_SECONDS", default=1800)

#: Ops-only BotFather automation for refilling the pool (ADR-0002 tier C). Never on a
#: customer request path; off unless deliberately enabled.
PROVISIONING_MTPROTO_ENABLED = env.bool("PROVISIONING_MTPROTO_ENABLED", default=False)
BOT_POOL_LOW_WATERMARK = env.int("BOT_POOL_LOW_WATERMARK", default=5)

# --------------------------------------------------------------------------- ai
# Provider abstraction (`apps/ai/providers/`) — only "anthropic" is implemented; adding a
# second provider is a new module there plus an entry in `providers/__init__.py`.
AI_PROVIDER = env("AI_PROVIDER", default="anthropic")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
# Cheap and fast by design: this answers customer-facing chat messages at volume under a
# hard per-bot token budget, not one-off high-stakes generations. A platform admin can
# move every tenant onto a different model without a deploy via `SystemSetting` key
# "ai.model" (`apps.ai.services.get_configured_model`).
AI_MODEL = env("AI_MODEL", default="claude-haiku-4-5")
AI_MAX_OUTPUT_TOKENS = env.int("AI_MAX_OUTPUT_TOKENS", default=1024)
AI_REQUEST_TIMEOUT_SECONDS = env.float("AI_REQUEST_TIMEOUT_SECONDS", default=20.0)
AI_MAX_DOCUMENT_CHARS = env.int("AI_MAX_DOCUMENT_CHARS", default=200_000)
#: A bot's own configured budget (`AiConfiguration.monthly_token_budget`), if any, is
#: clamped to this. This platform-wide figure is what applies when a bot has none.
AI_DEFAULT_MONTHLY_TOKEN_BUDGET = env.int("AI_DEFAULT_MONTHLY_TOKEN_BUDGET", default=200_000)
#: Enforced regardless of any per-bot override above — a safety ceiling nobody can raise
#: past, even by misconfiguration.
AI_HARD_MONTHLY_TOKEN_BUDGET_CAP = env.int("AI_HARD_MONTHLY_TOKEN_BUDGET_CAP", default=2_000_000)

# --------------------------------------------------------------------------- flags
MAINTENANCE_MODE = env.bool("MAINTENANCE_MODE", default=False)
FEATURE_BALE_ENABLED = env.bool("FEATURE_BALE_ENABLED", default=False)
FEATURE_AI_ENABLED = env.bool("FEATURE_AI_ENABLED", default=False)

# --------------------------------------------------------------------------- logging
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_secrets": {"()": "apps.core.logging.SecretRedactingFilter"},
        "request_id": {"()": "apps.core.logging.RequestIDFilter"},
    },
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        },
        #: Every field a log aggregator (CloudWatch, Loki, ...) wants pre-parsed:
        #: `timestamp`, `level`, `logger`, `event` (the message), `request_id`, and —
        #: when the request resolved one — `tenant_id`. See `apps.core.logging`.
        "json": {"()": "apps.core.logging.build_json_formatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            #: `verbose` (human-readable) everywhere by default; production.py switches
            #: this to `json` — still overridable per-deploy via `LOG_FORMAT`.
            "formatter": env("LOG_FORMAT", default="verbose"),
            "filters": ["request_id", "redact_secrets"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
