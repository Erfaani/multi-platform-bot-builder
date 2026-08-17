"""Notifications (spec §30).

A notification is stored once and delivered to many channels. Delivery is tracked per
channel so "the customer says they never got the email" is answerable.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PublicIdModel, TimeStampedModel


class Channel(models.TextChoices):
    WEB = "WEB", _("In-app")
    EMAIL = "EMAIL", _("Email")
    TELEGRAM = "TELEGRAM", _("Telegram")
    BALE = "BALE", _("Bale")


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    SENT = "SENT", _("Sent")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped")


class Notification(PublicIdModel, TimeStampedModel):
    recipient = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    tenant = models.ForeignKey(
        "customers.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    event_type = models.CharField(max_length=128, db_index=True)
    #: Translation keys, resolved at render time so a notification stored in English
    #: still reads correctly if the user later switches to Persian (I18N.md §1).
    title_key = models.CharField(max_length=128)
    body_key = models.CharField(max_length=128)
    params = models.JSONField(default=dict, blank=True)

    link = models.CharField(max_length=255, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["recipient", "-created_at"], name="notif_recipient_time_idx"),
            models.Index(fields=["tenant", "-created_at"], name="notif_tenant_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} → {self.recipient_id or self.tenant_id}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class NotificationDelivery(TimeStampedModel):
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "channel"], name="notification_channel_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.notification_id}/{self.channel}: {self.status}"
