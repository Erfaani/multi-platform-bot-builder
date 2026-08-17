"""Local development settings."""

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = INSTALLED_APPS + ["django_extensions"]

# A deterministic development KEK so encrypted values survive a restart.
# Never used outside local: production refuses to boot without a real one.
ENCRYPTION_KEK = env("ENCRYPTION_KEK", default="ZGV2LW9ubHkta2V5LTMyLWJ5dGVzLWxvbmchISEhISE=")

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
