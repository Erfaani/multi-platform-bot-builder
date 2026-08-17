"""Runtime tables: inbound updates, outbound messages, sessions, contacts."""

from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel, TimeStampedModel
from apps.platforms.constants import Platform


class InboundUpdate(models.Model):
    """Raw update as the platform sent it.

    Persisted *before* any processing so an update is never lost to a crash, and the
    unique constraint makes platform redelivery a no-op (BOT_RUNTIME.md §10).
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        PROCESSED = "PROCESSED", _("Processed")
        FAILED = "FAILED", _("Failed")
        IGNORED = "IGNORED", _("Ignored")

    instance = models.ForeignKey(
        "bots.BotPlatformInstance", on_delete=models.CASCADE, related_name="inbound_updates"
    )
    platform_update_id = models.BigIntegerField()
    raw = models.JSONField()

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "inbound_update"
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "platform_update_id"], name="inbound_update_uniq"
            )
        ]
        indexes = [models.Index(fields=["status", "received_at"], name="inbound_status_idx")]

    def __str__(self) -> str:
        return f"update {self.platform_update_id} for instance {self.instance_id}"


class OutboundMessage(TimeStampedModel):
    """Every send, recorded before dispatch.

    This is the audit trail and the answer to "my bot didn't reply" — a row with an
    error beats silence (BOT_RUNTIME.md §7).
    """

    class Status(models.TextChoices):
        QUEUED = "QUEUED", _("Queued")
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")
        DROPPED = "DROPPED", _("Dropped")

    instance = models.ForeignKey(
        "bots.BotPlatformInstance", on_delete=models.CASCADE, related_name="outbound_messages"
    )
    chat_ref = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    platform_message_id = models.CharField(max_length=64, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    #: Bulk sends (reminders, broadcasts) run at lower priority so they can never
    #: starve someone waiting for a reply.
    is_bulk = models.BooleanField(default=False)

    class Meta:
        db_table = "outbound_message"
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="outbound_retry_idx"),
        ]

    def __str__(self) -> str:
        return f"message to {self.chat_ref} ({self.status})"


class BusinessContact(TenantOwnedModel):
    """An end user of a customer's bot.

    Explicitly **not** a platform `User`: a clinic's patients have no login and must
    never appear in the accounts table (ARCHITECTURE.md §7).
    """

    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="contacts")
    platform = models.CharField(max_length=16, choices=Platform.choices)
    platform_user_id = models.CharField(max_length=64)

    display_name = models.CharField(max_length=128, blank=True)
    username = models.CharField(max_length=64, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    locale = models.CharField(max_length=8, blank=True)

    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    is_blocked = models.BooleanField(
        default=False, help_text=_("The user blocked the bot, or the chat is gone.")
    )

    class Meta:
        db_table = "business_contact"
        constraints = [
            models.UniqueConstraint(
                fields=["bot", "platform", "platform_user_id"], name="business_contact_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "-last_seen_at"], name="contact_tenant_seen_idx")
        ]

    def __str__(self) -> str:
        return self.display_name or self.platform_user_id


class BotSession(models.Model):
    """Durable copy of a conversation's state.

    Redis holds the hot copy; this row means a worker restart does not lose a
    half-finished booking (BOT_RUNTIME.md §4).
    """

    IDLE = "IDLE"

    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="sessions")
    platform = models.CharField(max_length=16, choices=Platform.choices)
    chat_ref = models.CharField(max_length=64)
    user_ref = models.CharField(max_length=64)

    state = models.CharField(max_length=64, default=IDLE)
    context = models.JSONField(default=dict, blank=True)
    locale = models.CharField(max_length=8, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "bot_session"
        constraints = [
            models.UniqueConstraint(
                fields=["bot", "platform", "chat_ref", "user_ref"], name="bot_session_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.chat_ref}/{self.user_ref}: {self.state}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()
