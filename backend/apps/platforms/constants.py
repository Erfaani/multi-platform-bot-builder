"""Platform identifiers.

One place, because these strings appear in the database (`FeaturePlatformAvailability`,
`BotPlatformInstance`), in price keys, in Celery queue names and in webhook URLs.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class Platform(models.TextChoices):
    TELEGRAM = "telegram", _("Telegram")
    BALE = "bale", _("Bale")


#: Adapters that can actually run a customer bot. `preview` is a rendering target
#: only — it must never be sellable, so it is deliberately absent here.
SELLABLE_PLATFORMS: tuple[str, ...] = (Platform.TELEGRAM, Platform.BALE)

PREVIEW = "preview"
