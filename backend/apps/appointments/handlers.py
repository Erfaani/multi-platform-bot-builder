"""The booking conversation (spec's appointment feature).

Every step is a plain, unsigned-state callback round trip — no `session.state` — because
every choice at every step is enumerable (a service, a staff member, a day, a slot) with
nothing free-text to collect. That keeps the whole flow stateless and exactly as
inspectable as `faq:list`'s list-then-detail pattern, and immune to the one failure mode
session-based flows have to guard against explicitly: a stale, half-finished booking
resuming days later against slots that no longer exist.

Selections accumulate on the callback payload itself: `service_pk`, then
`service_pk:staff_pk`, then `service_pk:staff_pk:epoch_minutes`. Every step re-validates
from scratch — a signed callback proves the *shape* of a request, never that the world
hasn't moved since it was minted.

Slot selection has no separate "pick a day" step: the four-step flow (service → staff →
slot → confirm) matches the one the preview catalogue already promises
(`apps/appointments/manifest.py`'s `PreviewStep` sequence, written in Phase 2 before this
module existed). `select_slot` scans forward across days itself and offers a single flat
list — the extra tap a day-then-time flow would add was never part of that promise.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from apps.bot_runtime.handlers import HandlerResult, command, route
from apps.core.errors import AppError
from apps.platforms.base import Choice, Reply

from apps.appointments import services
from apps.appointments.models import AppointmentService, StaffMember

MAX_SLOT_CHOICES = 15


def _menu_choices(ctx) -> list[Choice]:
    from apps.features.registry import manifests_for

    entries = sorted(
        (entry for manifest in manifests_for(ctx.enabled_features) for entry in manifest.menu),
        key=lambda entry: entry.sort_order,
    )
    return [Choice(label_key=entry.label_key, value=entry.route) for entry in entries]


def _menu_reply(ctx, text_key: str, **params) -> HandlerResult:
    return HandlerResult(reply=Reply(text_key=text_key, params=params, choices=_menu_choices(ctx)), next_state="IDLE")


def _service_or_none(ctx, service_pk: str) -> AppointmentService | None:
    return AppointmentService.objects.filter(bot_id=ctx.bot_id, pk=service_pk, is_active=True).first()


def _staff_or_none(ctx, staff_pk: str) -> StaffMember | None:
    return StaffMember.objects.filter(bot_id=ctx.bot_id, pk=staff_pk, is_active=True).first()


@route("appointment:book")
@command("book")
def start_booking(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    active = services.list_services(ctx.bot_id)
    if not active:
        return _menu_reply(ctx, "bot.appointment.no_services")

    return HandlerResult(
        reply=Reply(
            text_key="bot.appointment.select_service",
            choices=[
                Choice(label_key=f"literal:{s.name}", value=f"appointment:pick_staff.{s.pk}")
                for s in active
            ],
        ),
        next_state="IDLE",
    )


@route("appointment:pick_staff")
def pick_staff(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    service = _service_or_none(ctx, value)
    if service is None:
        return _menu_reply(ctx, "bot.appointment.expired")

    eligible = services.staff_for_service(ctx.bot_id, service)
    if not eligible:
        return _menu_reply(ctx, "bot.appointment.no_staff")

    if len(eligible) == 1:
        return _offer_slots(ctx, service, eligible[0])

    return HandlerResult(
        reply=Reply(
            text_key="bot.appointment.select_staff",
            choices=[
                Choice(label_key=f"literal:{s.name}", value=f"appointment:pick_slot.{service.pk}:{s.pk}")
                for s in eligible
            ],
        ),
        next_state="IDLE",
    )


@route("appointment:pick_slot")
def pick_slot(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    service_pk, _, staff_pk = value.partition(":")
    service = _service_or_none(ctx, service_pk)
    staff = _staff_or_none(ctx, staff_pk)
    if service is None or staff is None:
        return _menu_reply(ctx, "bot.appointment.expired")

    return _offer_slots(ctx, service, staff)


def _offer_slots(ctx, service: AppointmentService, staff: StaffMember) -> HandlerResult:
    """Scan forward day by day and offer the next `MAX_SLOT_CHOICES` open times."""
    tz = ZoneInfo(ctx.timezone or "UTC")
    today = datetime.now(tz).date()

    found = []
    for offset in range(services.BOOKING_WINDOW_DAYS + 1):
        day = today + timedelta(days=offset)
        found.extend(
            services.available_slots(
                bot_id=ctx.bot_id, timezone=ctx.timezone, service=service, staff=staff, day=day
            )
        )
        if len(found) >= MAX_SLOT_CHOICES:
            break

    if not found:
        return _menu_reply(ctx, "bot.appointment.no_availability")

    choices = [
        Choice(
            label_key=f"literal:{slot.starts_at.astimezone(tz).strftime('%a %b %d, %H:%M')}",
            value=(
                f"appointment:confirm.{service.pk}:{staff.pk}:"
                f"{int(slot.starts_at.timestamp() // 60)}"
            ),
        )
        for slot in found[:MAX_SLOT_CHOICES]
    ]
    return HandlerResult(
        reply=Reply(text_key="bot.appointment.select_slot", choices=choices), next_state="IDLE"
    )


@route("appointment:confirm")
def confirm(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    from apps.bots.models import Bot
    from apps.bot_runtime.models import BusinessContact

    service_pk, _, rest = value.partition(":")
    staff_pk, _, epoch_minutes = rest.partition(":")
    service = _service_or_none(ctx, service_pk)
    staff = _staff_or_none(ctx, staff_pk)
    if service is None or staff is None or not epoch_minutes.lstrip("-").isdigit():
        return _menu_reply(ctx, "bot.appointment.expired")

    starts_at = datetime.fromtimestamp(int(epoch_minutes) * 60, tz=dt_timezone.utc)

    bot = Bot.objects.select_related("tenant").get(pk=ctx.bot_id)
    contact = BusinessContact.objects.get(
        bot_id=ctx.bot_id, platform=ctx.platform, platform_user_id=event.user_ref
    )

    try:
        appointment = services.book_appointment(
            bot=bot, contact=contact, service=service, staff=staff, starts_at=starts_at
        )
    except AppError:
        return _menu_reply(ctx, "bot.appointment.slot_taken")

    tz = ZoneInfo(ctx.timezone or "UTC")
    local = appointment.starts_at.astimezone(tz)
    return _menu_reply(
        ctx,
        "bot.appointment.confirmed",
        service=service.name,
        staff=staff.name,
        date=local.strftime("%Y-%m-%d"),
        time=local.strftime("%H:%M"),
    )
