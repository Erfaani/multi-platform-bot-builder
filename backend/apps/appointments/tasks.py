"""Appointment reminders — the `appointment_reminders` feature's entire job.

Runs on Celery beat, not triggered by an event: nothing "happens" at reminder time
except time passing, so a periodic sweep is the only mechanism that makes sense here.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus

logger = logging.getLogger(__name__)

#: How far ahead of the appointment the reminder goes out.
REMINDER_LEAD_MINUTES = 60
#: Sweep interval — wide enough relative to the lead time that no appointment can slip
#: between two runs unreminded.
SWEEP_INTERVAL_SECONDS = 300


@shared_task(ignore_result=True)
def send_due_reminders() -> int:
    """Send a reminder for every confirmed appointment now inside the lead window.

    Idempotent by construction: `reminder_sent_at` is set in the same call that sends,
    so an appointment already reminded never matches the query again — safe under
    Celery's at-least-once delivery even if this task itself is redelivered.
    """
    from apps.bot_runtime.context import BotContext, resolve_context
    from apps.bot_runtime.gateway import deliver
    from apps.bots.models import BotPlatformInstance
    from apps.platforms.base import RenderContext, Reply
    from apps.platforms.preview.messages import translate
    from apps.platforms.registry import capabilities_for
    from apps.platforms.rendering import render_with_capabilities

    now = timezone.now()
    window_end = now + timezone.timedelta(minutes=REMINDER_LEAD_MINUTES)

    due = (
        Appointment.objects.filter(
            status=AppointmentStatus.CONFIRMED,
            reminder_sent_at__isnull=True,
            starts_at__gte=now,
            starts_at__lte=window_end,
        )
        .select_related("bot", "contact", "service", "staff")
    )

    sent = 0
    for appointment in due:
        instance = BotPlatformInstance.objects.filter(
            bot_id=appointment.bot_id,
            platform=appointment.contact.platform,
            status=BotPlatformInstance.Status.ACTIVE,
        ).first()
        if instance is None:
            continue

        try:
            ctx = resolve_context(instance)
            if not ctx.has_feature("appointment_reminders"):
                continue
            local = appointment.starts_at.astimezone(_zone(appointment.business_timezone))
            reply = Reply(
                text_key="bot.appointment.reminder",
                params={
                    "service": appointment.service.name,
                    "staff": appointment.staff.name,
                    "time": local.strftime("%H:%M"),
                },
            )
            render_ctx = RenderContext(locale=ctx.default_locale, business_name=ctx.bot_name, translate=translate)
            message = render_with_capabilities(reply, render_ctx, capabilities_for(ctx.platform))
            deliver(
                instance=instance,
                # Telegram/Bale private chats: chat id equals the user id — there is no
                # group-chat case for these bots, so this is always the right target.
                chat_ref=appointment.contact.platform_user_id,
                message=message,
                is_bulk=True,
            )
        except Exception:
            logger.exception("Failed to send reminder for appointment %s", appointment.public_id)
            continue

        Appointment.objects.filter(pk=appointment.pk, reminder_sent_at__isnull=True).update(
            reminder_sent_at=now
        )
        sent += 1

    return sent


def _zone(name: str):
    from zoneinfo import ZoneInfo

    return ZoneInfo(name or "UTC")
