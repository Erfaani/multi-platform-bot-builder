"""Provisioning saga state.

Modelled as explicit rows rather than a chain of side effects, because Celery is
at-least-once: a retry must *resume* at the first unfinished step, not replay the ones
that already succeeded (BOT_RUNTIME.md §11).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PublicIdModel, TimeStampedModel


class JobStatus(models.TextChoices):
    QUEUED = "QUEUED", _("Queued")
    RUNNING = "RUNNING", _("Running")
    #: Tier B: a paid order legitimately waits here until the customer pastes a token.
    #: This is a resting state, not a failure — the saga must never time it out.
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER", _("Waiting for the customer")
    SUCCEEDED = "SUCCEEDED", _("Succeeded")
    FAILED = "FAILED", _("Failed")
    COMPENSATING = "COMPENSATING", _("Compensating")
    COMPENSATED = "COMPENSATED", _("Compensated")


class StepStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    SUCCEEDED = "SUCCEEDED", _("Succeeded")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped")
    BLOCKED = "BLOCKED", _("Blocked on the customer")


class ProvisioningJob(PublicIdModel, TimeStampedModel):
    order = models.ForeignKey(
        "orders.Order", on_delete=models.CASCADE, related_name="provisioning_jobs"
    )
    bot = models.ForeignKey(
        "bots.Bot", null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    strategy = models.CharField(max_length=24)

    status = models.CharField(
        max_length=24, choices=JobStatus.choices, default=JobStatus.QUEUED, db_index=True
    )
    attempt = models.PositiveSmallIntegerField(default=0)

    #: Unique per order, so a duplicated `OrderPaid` event cannot start two sagas.
    idempotency_key = models.CharField(max_length=128, unique=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_detail = models.TextField(blank=True)

    class Meta:
        db_table = "provisioning_job"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"provisioning for order {self.order_id} ({self.status})"

    @property
    def is_resumable(self) -> bool:
        return self.status in {
            JobStatus.FAILED,
            JobStatus.QUEUED,
            JobStatus.AWAITING_CUSTOMER,
            JobStatus.RUNNING,
        }


class ProvisioningStep(TimeStampedModel):
    job = models.ForeignKey(ProvisioningJob, on_delete=models.CASCADE, related_name="steps")
    step_slug = models.CharField(max_length=64)
    sequence = models.PositiveSmallIntegerField()

    status = models.CharField(
        max_length=16, choices=StepStatus.choices, default=StepStatus.PENDING
    )
    attempt = models.PositiveSmallIntegerField(default=0)

    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provisioning_step"
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(fields=["job", "step_slug"], name="provisioning_step_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.step_slug} ({self.status})"
