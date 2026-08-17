"""Bots and their platform instances.

A bot is a set of rows, not a process or a container (spec §21). One runtime serves
every bot on the platform.

The credential model is the security centre of gravity here: a bot token grants full
control of a customer's bot, so it is envelope-encrypted, never serialized, never logged,
and has no admin read view.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import (
    CurrencyCodeField,
    PublicIdModel,
    TenantOwnedModel,
    TimeStampedModel,
)
from apps.platforms.constants import Platform


class BotStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    PROVISIONING = "PROVISIONING", _("Provisioning")
    ACTIVE = "ACTIVE", _("Active")
    SUSPENDED = "SUSPENDED", _("Suspended")
    FAILED = "FAILED", _("Failed")
    ARCHIVED = "ARCHIVED", _("Archived")


class AcquisitionMode(models.TextChoices):
    """How we came to hold this bot's credential (ADR-0002)."""

    POOL = "POOL", _("Assigned from the platform pool")
    TOKEN_HANDOFF = "TOKEN_HANDOFF", _("Customer supplied the token")
    MTPROTO = "MTPROTO", _("Created by the operations tool")


class Bot(PublicIdModel, TenantOwnedModel):
    #: The order that created it. Renewals and upgrades create further orders, so this is
    #: the *origin*, not "the" order (docs/01-ARCHITECTURE-REVIEW.md F-7).
    origin_order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="bots"
    )
    template = models.ForeignKey(
        "business_templates.BusinessTemplate", on_delete=models.PROTECT, related_name="bots"
    )

    name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16, choices=BotStatus.choices, default=BotStatus.DRAFT, db_index=True
    )

    default_locale = models.CharField(max_length=8, default="en")
    timezone = models.CharField(max_length=64, default="UTC")
    currency = CurrencyCodeField(default="USD")

    last_activity_at = models.DateTimeField(null=True, blank=True)
    error_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "bot"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["tenant", "status"], name="bot_tenant_status_idx")]

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == BotStatus.ACTIVE

    def has_feature(self, slug: str) -> bool:
        """For service-layer code that only has a `Bot`, not a `BotContext`.

        The runtime's hot dispatch path uses `BotContext.has_feature` (cached, in-memory)
        instead — this hits the database and exists for the comparatively rare call from
        outside a single dispatch, e.g. deciding whether to publish an owner-notification
        event after a booking.
        """
        return self.bot_features.filter(feature__slug=slug, is_enabled=True).exists()


class BotPlatformInstance(PublicIdModel, TimeStampedModel):
    """One bot running on one channel. A multi-platform bot has several of these,
    all sharing the same configuration and business data (spec §3).
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        AWAITING_TOKEN = "AWAITING_TOKEN", _("Waiting for the customer's token")
        CONFIGURING = "CONFIGURING", _("Configuring")
        ACTIVE = "ACTIVE", _("Active")
        SUSPENDED = "SUSPENDED", _("Suspended")
        FAILED = "FAILED", _("Failed")

    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="instances")
    platform = models.CharField(max_length=16, choices=Platform.choices)

    platform_bot_id = models.CharField(max_length=64, blank=True)
    username = models.CharField(max_length=64, blank=True)
    display_name = models.CharField(max_length=128, blank=True)

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    acquisition_mode = models.CharField(max_length=24, choices=AcquisitionMode.choices)

    webhook_url = models.URLField(blank=True)
    webhook_set_at = models.DateTimeField(null=True, blank=True)

    last_update_at = models.DateTimeField(null=True, blank=True)
    last_send_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bot_platform_instance"
        constraints = [
            models.UniqueConstraint(fields=["bot", "platform"], name="bot_platform_uniq"),
            # One Telegram bot cannot back two customers' instances.
            models.UniqueConstraint(
                fields=["platform", "platform_bot_id"],
                condition=~models.Q(platform_bot_id=""),
                name="platform_bot_id_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"@{self.username or '?'} ({self.platform})"

    @property
    def link(self) -> str:
        if not self.username:
            return ""
        return {
            Platform.TELEGRAM: f"https://t.me/{self.username}",
            Platform.BALE: f"https://ble.ir/{self.username}",
        }.get(self.platform, "")


class BotCredential(TimeStampedModel):
    """An envelope-encrypted bot token.

    Never serialized, never logged, no admin read view. `fingerprint` allows equality
    checks ("is this token already registered?") without ever decrypting or holding two
    plaintexts side by side (SECURITY.md §5).
    """

    instance = models.OneToOneField(
        BotPlatformInstance, on_delete=models.CASCADE, related_name="credential"
    )
    ciphertext = models.BinaryField()
    kek_version = models.PositiveSmallIntegerField(default=1)
    fingerprint = models.CharField(max_length=64, unique=True)
    rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bot_credential"

    def __str__(self) -> str:
        # Deliberately reveals nothing about the token.
        return f"credential for instance {self.instance_id}"


class WebhookSecret(TimeStampedModel):
    """Per-bot webhook secret.

    Two rows may be active at once so a secret can be rotated without dropping updates
    mid-flight (BOT_RUNTIME.md §2).
    """

    instance = models.ForeignKey(
        BotPlatformInstance, on_delete=models.CASCADE, related_name="webhook_secrets"
    )
    secret_hash = models.CharField(max_length=64, db_index=True)
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "webhook_secret"
        ordering = ("-valid_from",)

    def __str__(self) -> str:
        return f"secret for instance {self.instance_id}"


class BotConfiguration(TimeStampedModel):
    """Everything customer-specific about a bot's behaviour.

    `version` is bumped on every change and forms part of the runtime cache key, so a
    configuration edit invalidates the cache with no broadcast and no stale window
    (BOT_RUNTIME.md §3).
    """

    bot = models.OneToOneField(Bot, on_delete=models.CASCADE, related_name="configuration")

    welcome_message = models.TextField(blank=True)
    menu = models.JSONField(default=list, blank=True)
    branding = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "bot_configuration"

    def __str__(self) -> str:
        return f"configuration v{self.version} for {self.bot_id}"

    def bump(self) -> None:
        BotConfiguration.objects.filter(pk=self.pk).update(version=models.F("version") + 1)
        self.refresh_from_db(fields=["version"])


class BotFeature(TimeStampedModel):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="bot_features")
    feature = models.ForeignKey(
        "features.Feature", on_delete=models.PROTECT, related_name="bot_features"
    )
    is_enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    source_order_item = models.ForeignKey(
        "orders.OrderItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "bot_feature"
        constraints = [
            models.UniqueConstraint(fields=["bot", "feature"], name="bot_feature_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.bot_id}:{self.feature_id}"


class BotPoolEntry(TimeStampedModel):
    """A pre-created bot awaiting assignment (ADR-0002, tier A).

    Operations stocks these so a paying customer can be live in seconds with no action
    on their part. The trade-off is a platform-generated username.
    """

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", _("Available")
        RESERVED = "RESERVED", _("Reserved")
        ASSIGNED = "ASSIGNED", _("Assigned")
        RETIRED = "RETIRED", _("Retired")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    platform = models.CharField(max_length=16, choices=Platform.choices)
    username = models.CharField(max_length=64)
    platform_bot_id = models.CharField(max_length=64, blank=True)

    #: Encrypted here until assignment, then moved onto the instance's credential.
    ciphertext = models.BinaryField()
    kek_version = models.PositiveSmallIntegerField(default=1)
    fingerprint = models.CharField(max_length=64, unique=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.AVAILABLE, db_index=True
    )
    reserved_until = models.DateTimeField(null=True, blank=True)
    assigned_instance = models.OneToOneField(
        BotPlatformInstance,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pool_entry",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "bot_pool_entry"
        ordering = ("platform", "username")
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "username"], name="pool_platform_username_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["platform", "status"], name="pool_platform_status_idx")
        ]

    def __str__(self) -> str:
        return f"@{self.username} ({self.status})"
