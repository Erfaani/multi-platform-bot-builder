"""Appointment booking use cases.

Slot computation reads `apps.businesses.models.WorkingHours` — the same table the
dashboard already edits for "opening hours" — rather than a second, appointment-specific
schedule. Per-staff schedules are a real feature this does not build yet: every staff
member currently shares the bot's one weekly schedule (see `WorkingHours`'s own docstring,
which already flagged per-weekday hours as "for the appointment module" — this is that
module using them for the first time, just not yet the per-staff variant).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone as dj_timezone

from apps.audit.services import record_audit
from apps.businesses.models import WorkingHours
from apps.core.errors import ConflictError, NotFoundError, ValidationError
from apps.core.events import publish

from apps.appointments.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentService,
    AppointmentStatus,
    StaffMember,
    TimeOff,
)

#: How far ahead a customer may book, and how much lead time a same-day slot needs.
BOOKING_WINDOW_DAYS = 21
MIN_LEAD_MINUTES = 30

# --------------------------------------------------------------------------- services


def list_services(bot_id: int) -> list[AppointmentService]:
    return list(
        AppointmentService.objects.filter(bot_id=bot_id, is_active=True).order_by("sort_order", "id")
    )


@transaction.atomic
def create_service(*, bot, actor, name: str, duration_minutes: int, **fields) -> AppointmentService:
    name = name.strip()
    if not name:
        raise ValidationError(code="appointment.service_name_required", field_errors={"name": ["Required."]})
    if duration_minutes <= 0:
        raise ValidationError(
            code="appointment.invalid_duration", field_errors={"duration_minutes": ["Must be positive."]}
        )

    service = AppointmentService.objects.create(
        tenant=bot.tenant,
        bot=bot,
        name=name[:128],
        duration_minutes=duration_minutes,
        buffer_minutes=fields.get("buffer_minutes", 0),
        description=fields.get("description", ""),
        price_minor=fields.get("price_minor", 0),
        currency=fields.get("currency", bot.currency),
        sort_order=fields.get("sort_order", 100),
    )
    bot.configuration.bump()
    record_audit(
        actor=actor, action="appointment_service.created", resource_type="appointment_service",
        resource_id=str(service.pk), tenant=bot.tenant,
    )
    return service


@transaction.atomic
def update_service(*, bot, service_id: int, actor, **fields) -> AppointmentService:
    service = AppointmentService.objects.filter(bot=bot, pk=service_id).first()
    if service is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in ("name", "description", "duration_minutes", "buffer_minutes", "price_minor", "currency", "is_active", "sort_order"):
        if key in fields and fields[key] is not None:
            setattr(service, key, fields[key])
            changed.append(key)

    if changed:
        service.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor, action="appointment_service.updated", resource_type="appointment_service",
            resource_id=str(service.pk), tenant=bot.tenant, metadata={"fields": changed},
        )
    return service


@transaction.atomic
def delete_service(*, bot, service_id: int, actor) -> None:
    service = AppointmentService.objects.filter(bot=bot, pk=service_id).first()
    if service is None:
        raise NotFoundError()
    service.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="appointment_service.deleted", resource_type="appointment_service",
        resource_id=str(service_id), tenant=bot.tenant,
    )


# --------------------------------------------------------------------------- staff


def list_staff(bot_id: int) -> list[StaffMember]:
    return list(
        StaffMember.objects.filter(bot_id=bot_id, is_active=True)
        .prefetch_related("services")
        .order_by("sort_order", "id")
    )


def get_or_create_default_staff(bot) -> StaffMember:
    """Booking must never be blocked on "nobody configured a calendar yet"."""
    existing = StaffMember.objects.filter(bot=bot, is_active=True).order_by("sort_order", "id").first()
    if existing is not None:
        return existing
    return StaffMember.objects.create(tenant=bot.tenant, bot=bot, name=bot.name)


@transaction.atomic
def create_staff(*, bot, actor, name: str, service_ids: list[int] | None = None) -> StaffMember:
    name = name.strip()
    if not name:
        raise ValidationError(code="appointment.staff_name_required", field_errors={"name": ["Required."]})

    staff = StaffMember.objects.create(tenant=bot.tenant, bot=bot, name=name[:128])
    if service_ids:
        staff.services.set(AppointmentService.objects.filter(bot=bot, pk__in=service_ids))
    bot.configuration.bump()
    record_audit(
        actor=actor, action="staff_member.created", resource_type="staff_member",
        resource_id=str(staff.pk), tenant=bot.tenant,
    )
    return staff


@transaction.atomic
def update_staff(*, bot, staff_id: int, actor, service_ids: list[int] | None = None, **fields) -> StaffMember:
    staff = StaffMember.objects.filter(bot=bot, pk=staff_id).first()
    if staff is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in ("name", "is_active", "sort_order"):
        if key in fields and fields[key] is not None:
            setattr(staff, key, fields[key])
            changed.append(key)
    if changed:
        staff.save(update_fields=[*changed, "updated_at"])

    if service_ids is not None:
        staff.services.set(AppointmentService.objects.filter(bot=bot, pk__in=service_ids))
        changed.append("services")

    if changed:
        bot.configuration.bump()
        record_audit(
            actor=actor, action="staff_member.updated", resource_type="staff_member",
            resource_id=str(staff.pk), tenant=bot.tenant, metadata={"fields": changed},
        )
    return staff


@transaction.atomic
def delete_staff(*, bot, staff_id: int, actor) -> None:
    staff = StaffMember.objects.filter(bot=bot, pk=staff_id).first()
    if staff is None:
        raise NotFoundError()
    staff.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="staff_member.deleted", resource_type="staff_member",
        resource_id=str(staff_id), tenant=bot.tenant,
    )


def staff_for_service(bot_id: int, service: AppointmentService) -> list[StaffMember]:
    return [s for s in list_staff(bot_id) if s.performs(service)]


# --------------------------------------------------------------------------- slots


@dataclass(frozen=True, slots=True)
class Slot:
    starts_at: datetime  # UTC
    ends_at: datetime  # UTC


def _day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The local calendar day's [start, end) expressed in UTC.

    Never `starts_at__date` on the UTC column directly — a slot at 23:30 local time can
    already be tomorrow in UTC in some timezones, and a date-cast on the stored column
    would silently miss or misfile it.
    """
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(ZoneInfo("UTC"))
    return start, start + timedelta(days=1)


def _local_windows(
    bot_id: int, staff: StaffMember, day: date, tz: ZoneInfo, day_start: datetime, day_end: datetime
) -> list[tuple[datetime, datetime]]:
    """Open intervals for `day`, in UTC, after subtracting time off."""
    weekday = day.weekday()
    rows = WorkingHours.objects.filter(bot_id=bot_id, weekday=weekday, is_closed=False).exclude(
        opens_at__isnull=True
    ).exclude(closes_at__isnull=True)

    windows: list[tuple[datetime, datetime]] = []
    for row in rows:
        opens = datetime.combine(day, row.opens_at, tzinfo=tz).astimezone(ZoneInfo("UTC"))
        closes = datetime.combine(day, row.closes_at, tzinfo=tz).astimezone(ZoneInfo("UTC"))
        if closes > opens:
            windows.append((opens, closes))

    time_off = TimeOff.objects.filter(bot_id=bot_id, starts_at__lt=day_end, ends_at__gt=day_start).filter(
        Q(staff__isnull=True) | Q(staff=staff)
    )
    for off in time_off:
        windows = _subtract(windows, (off.starts_at, off.ends_at))

    return windows


def _subtract(
    windows: list[tuple[datetime, datetime]], blocked: tuple[datetime, datetime]
) -> list[tuple[datetime, datetime]]:
    result: list[tuple[datetime, datetime]] = []
    b_start, b_end = blocked
    for start, end in windows:
        if b_end <= start or b_start >= end:
            result.append((start, end))
            continue
        if b_start > start:
            result.append((start, b_start))
        if b_end < end:
            result.append((b_end, end))
    return result


def available_slots(
    *, bot_id: int, timezone: str, service: AppointmentService, staff: StaffMember, day: date
) -> list[Slot]:
    if not staff.performs(service):
        raise ValidationError(
            code="appointment.staff_does_not_perform_service",
            message="This staff member does not offer that service.",
        )

    tz = ZoneInfo(timezone or "UTC")
    today_local = dj_timezone.now().astimezone(tz).date()
    if day < today_local or day > today_local + timedelta(days=BOOKING_WINDOW_DAYS):
        return []

    step = timedelta(minutes=service.duration_minutes)
    padded = timedelta(minutes=service.duration_minutes + service.buffer_minutes)
    earliest = dj_timezone.now() + timedelta(minutes=MIN_LEAD_MINUTES)

    day_start, day_end = _day_bounds_utc(day, tz)
    busy = list(
        Appointment.objects.filter(staff=staff, status__in=ACTIVE_STATUSES)
        .filter(starts_at__lt=day_end, ends_at__gt=day_start)
        .values_list("starts_at", "ends_at")
    )

    slots: list[Slot] = []
    for window_start, window_end in _local_windows(bot_id, staff, day, tz, day_start, day_end):
        cursor = window_start
        while cursor + padded <= window_end:
            slot_end = cursor + step
            if cursor >= earliest and not any(cursor < b_end and slot_end > b_start for b_start, b_end in busy):
                slots.append(Slot(starts_at=cursor, ends_at=slot_end))
            cursor += step
    return slots


# --------------------------------------------------------------------------- booking


@transaction.atomic
def book_appointment(*, bot, contact, service: AppointmentService, staff: StaffMember, starts_at: datetime) -> Appointment:
    if not staff.performs(service):
        raise ValidationError(
            code="appointment.staff_does_not_perform_service",
            message="This staff member does not offer that service.",
        )
    if starts_at < dj_timezone.now():
        raise ConflictError(code="appointment.slot_in_the_past", message="That time has already passed.")

    ends_at = starts_at + timedelta(minutes=service.duration_minutes)

    try:
        with transaction.atomic():
            appointment = Appointment.objects.create(
                tenant=bot.tenant,
                bot=bot,
                contact=contact,
                service=service,
                staff=staff,
                starts_at=starts_at,
                ends_at=ends_at,
                business_timezone=bot.timezone or "UTC",
                status=AppointmentStatus.CONFIRMED,
            )
    except IntegrityError as exc:
        # The final backstop: the EXCLUDE constraint caught a race the availability
        # check above could not, because two requests read "free" at the same instant.
        raise ConflictError(
            code="appointment.slot_taken", message="That time was just booked by someone else."
        ) from exc

    record_audit(
        actor=None, action="appointment.booked", resource_type="appointment",
        resource_id=str(appointment.public_id), tenant=bot.tenant,
        metadata={"service": service.name, "staff": staff.name, "starts_at": starts_at.isoformat()},
    )
    publish(
        "appointment.booked",
        {
            "tenant_id": str(bot.tenant.public_id),
            "bot_id": str(bot.public_id),
            "appointment_id": str(appointment.public_id),
            "dedupe_key": f"appointment:{appointment.public_id}",
            "service": service.name,
            "staff": staff.name,
            "starts_at": starts_at.isoformat(),
        },
    )
    return appointment


@transaction.atomic
def cancel_appointment(*, appointment: Appointment, actor, reason: str = "") -> Appointment:
    locked = Appointment.objects.select_for_update().get(pk=appointment.pk)
    if locked.status != AppointmentStatus.CONFIRMED:
        raise ConflictError(code="appointment.not_cancellable", message="This appointment cannot be cancelled.")

    locked.status = AppointmentStatus.CANCELLED
    locked.cancellation_reason = reason[:255]
    locked.save(update_fields=["status", "cancellation_reason", "updated_at"])

    record_audit(
        actor=actor, action="appointment.cancelled", resource_type="appointment",
        resource_id=str(locked.public_id), tenant=locked.tenant, metadata={"reason": reason},
    )
    return locked


def list_appointments(bot, *, since=None, upcoming_only: bool = True) -> list[Appointment]:
    qs = Appointment.objects.filter(bot=bot).select_related("service", "staff", "contact")
    if upcoming_only:
        qs = qs.filter(starts_at__gte=since or dj_timezone.now())
    return list(qs.order_by("starts_at"))
