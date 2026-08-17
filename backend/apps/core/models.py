"""Base models and platform-wide tables.

Everything tenant-owned inherits :class:`TenantOwnedModel`; see ADR-0005.
"""

from __future__ import annotations

import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.managers import TenantManager


class CurrencyCodeField(models.CharField):
    """ISO-4217 code, or a crypto ticker such as USDT."""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("max_length", 8)
        super().__init__(**kwargs)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    """Externally addressable objects expose a UUID, never their sequential PK.

    Sequential IDs leak business volume and invite enumeration (SECURITY.md §4).
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True


class TenantOwnedModel(TimeStampedModel):
    """Base for every customer-owned record.

    ``tenant`` is non-null by design: a row that cannot name its owner is a leak
    waiting to happen. Subclasses should index ``(tenant, <their lookup>)``.
    """

    tenant = models.ForeignKey(
        "customers.Tenant",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    objects = TenantManager()

    class Meta:
        abstract = True


class Currency(TimeStampedModel):
    """Currency registry.

    ``display_unit``/``display_divisor`` exist for Toman, which is a *presentation
    unit* of IRR (÷10) rather than a currency of its own — ADR-0004.
    """

    code = CurrencyCodeField(primary_key=True)
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, blank=True)
    exponent = models.PositiveSmallIntegerField(
        help_text=_("Decimal places: IRR 0, USD 2, USDT 6, BTC 8."),
    )
    display_unit = models.CharField(
        max_length=16,
        blank=True,
        help_text=_("Optional presentation unit, e.g. TOMAN for IRR."),
    )
    display_divisor = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_("Divisor applied to reach the display unit, e.g. 10 for Toman."),
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "currency"
        ordering = ("sort_order", "code")
        verbose_name_plural = "currencies"

    def __str__(self) -> str:
        return self.code


class SystemSetting(TimeStampedModel):
    """Admin-editable platform configuration (spec §51).

    Secrets never live here — they stay in environment variables (SECURITY.md §12).
    """

    key = models.CharField(max_length=128, unique=True)
    value = models.JSONField(default=dict)
    value_type = models.CharField(max_length=16, default="json")
    description = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(
        default=False,
        help_text=_("Safe to expose to unauthenticated frontend clients."),
    )
    updated_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "system_setting"
        ordering = ("key",)

    def __str__(self) -> str:
        return self.key


class OutboxMessage(models.Model):
    """Transactional outbox.

    Domain events are written here in the same transaction as the state change they
    describe, so "the order was paid but the email never sent" cannot happen
    (ARCHITECTURE.md §9). A relay task publishes them to Celery.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        PUBLISHED = "PUBLISHED", _("Published")
        FAILED = "FAILED", _("Failed")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    event_type = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        db_table = "outbox_message"
        ordering = ("occurred_at",)
        indexes = [models.Index(fields=["status", "occurred_at"], name="outbox_status_time_idx")]

    def __str__(self) -> str:
        return f"{self.event_type} ({self.status})"


class IdempotencyRecord(TimeStampedModel):
    """Backs the ``Idempotency-Key`` contract (API.md §1).

    A replay carrying a *different* request fingerprint is rejected rather than
    silently answered with an unrelated stored response.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        COMPLETED = "COMPLETED", _("Completed")

    key = models.CharField(max_length=255)
    endpoint = models.CharField(max_length=255)
    user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "idempotency_record"
        constraints = [
            models.UniqueConstraint(fields=["key", "endpoint"], name="idempotency_key_endpoint_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.endpoint}:{self.key}"


class FailedTaskLog(TimeStampedModel):
    """Durable, operator-visible record of a Celery task that failed for good.

    Populated by the `task_failure` signal (`apps.core.celery_signals`), which Celery
    fires only once a task is *done* retrying — never on an attempt that will retry
    again (that is `task_retry`, a different signal, and normal recovery, not
    something an operator needs to see). This is deliberately independent of any
    domain-specific failure tracking a task already keeps for itself
    (`ProvisioningJob.error_code`, `OutboxMessage.last_error`, ...): those answer
    "why is this one order/message stuck"; this answers "which Celery tasks are
    dying" across the whole system, without needing to already know which domain
    model to go look at.
    """

    task_name = models.CharField(max_length=255, db_index=True)
    task_id = models.CharField(max_length=64, blank=True)
    args = models.JSONField(default=list, blank=True)
    kwargs = models.JSONField(default=dict, blank=True)
    exception_type = models.CharField(max_length=255, blank=True)
    exception_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)
    request_id = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "failed_task_log"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["task_name", "created_at"], name="failedtask_name_time_idx")]

    def __str__(self) -> str:
        return f"{self.task_name} ({self.exception_type})"
