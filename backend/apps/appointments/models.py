"""Appointment booking (DATABASE.md §9, spec's clinic/beauty/services templates).

Staff is mandatory on a booking, never optional: a solo practitioner still gets one
`StaffMember` row (created automatically the first time booking is used), so the
double-booking guard below always has a real resource to exclude on. A nullable staff
column would silently turn off that protection for every single-provider business —
exactly the shops this feature launches for first.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TenantOwnedModel
from apps.core.money import MoneyProxy


class AppointmentService(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="appointment_services")

    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveSmallIntegerField()
    #: Gap kept free after the appointment (cleaning, notes) before the slot is offered
    #: again — not shown to the customer, just reserved.
    buffer_minutes = models.PositiveSmallIntegerField(default=0)

    #: Informational only — nothing here is billed through `apps.pricing`. A clinic's own
    #: price for "teeth cleaning" has nothing to do with what the clinic pays this platform.
    price_minor = models.BigIntegerField(default=0)
    currency = CurrencyCodeField(blank=True)
    price = MoneyProxy("price_minor", "currency")

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "appointment_service"
        ordering = ("sort_order", "id")
        indexes = [models.Index(fields=["bot", "is_active"], name="appt_service_bot_active_idx")]

    def __str__(self) -> str:
        return self.name


class StaffMember(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="staff_members")
    name = models.CharField(max_length=128)
    #: Empty means "performs every active service" — the common single-provider case,
    #: where forcing an explicit assignment would just be a form to fill for no reason.
    services = models.ManyToManyField(AppointmentService, blank=True, related_name="staff")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "staff_member"
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.name

    def performs(self, service: AppointmentService) -> bool:
        return not self.services.exists() or self.services.filter(pk=service.pk).exists()


class TimeOff(TenantOwnedModel):
    """A block of time nobody can be booked in — a holiday, a day off, a closure."""

    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="time_off")
    #: Null means the whole business is closed, not just one staff member.
    staff = models.ForeignKey(
        StaffMember, null=True, blank=True, on_delete=models.CASCADE, related_name="time_off"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "time_off"
        ordering = ("starts_at",)
        indexes = [models.Index(fields=["bot", "starts_at", "ends_at"], name="time_off_bot_range_idx")]

    def __str__(self) -> str:
        return f"{self.staff or 'business'} off {self.starts_at}–{self.ends_at}"


class AppointmentStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", _("Confirmed")
    CANCELLED = "CANCELLED", _("Cancelled")
    COMPLETED = "COMPLETED", _("Completed")
    NO_SHOW = "NO_SHOW", _("No-show")


#: Statuses that still hold the slot — used both by the overlap guard and by anything
#: that needs to know "is this appointment still going to happen".
ACTIVE_STATUSES = (AppointmentStatus.CONFIRMED,)


class Appointment(PublicIdModel, TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="appointments")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact", on_delete=models.CASCADE, related_name="appointments"
    )
    service = models.ForeignKey(AppointmentService, on_delete=models.PROTECT, related_name="appointments")
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name="appointments")

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    #: What the customer was shown at booking time — `starts_at`/`ends_at` are UTC, and a
    #: DST change between booking and the appointment must not silently shift the wall-clock
    #: time a human agreed to.
    business_timezone = models.CharField(max_length=64)

    status = models.CharField(
        max_length=16, choices=AppointmentStatus.choices, default=AppointmentStatus.CONFIRMED
    )
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "appointment"
        ordering = ("starts_at",)
        indexes = [
            models.Index(fields=["bot", "starts_at"], name="appointment_bot_starts_idx"),
            models.Index(fields=["staff", "starts_at"], name="appointment_staff_starts_idx"),
        ]
        # The actual double-booking guard is a PostgreSQL EXCLUDE constraint added in
        # this app's initial migration via raw SQL — Django's `ExclusionConstraint`
        # wants a stored range column, and adding one purely to satisfy the ORM API
        # would duplicate `starts_at`/`ends_at` for no benefit over `tstzrange()` computed
        # inline. See `0001_initial.py`.

    def __str__(self) -> str:
        return f"{self.service} with {self.staff} at {self.starts_at}"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES
