"""The expiry sweep — this phase's entire "on schedule" mechanism.

Same shape as `apps.appointments.tasks.send_due_reminders`: nothing "happens" at expiry
except time passing, so a periodic sweep is the only mechanism that makes sense, and every
step is idempotent by construction (`services.py`'s status guards) so Celery's
at-least-once delivery can never double-suspend or double-notify.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.core.events import publish
from apps.orders.domain.state_machine import Actor
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.subscriptions.services import RENEWAL_REMINDER_DAYS, enter_grace_period, suspend

logger = logging.getLogger(__name__)

#: Coarse is fine — billing periods are day-granularity, not minute-granularity.
SWEEP_INTERVAL_SECONDS = 3600


@shared_task(ignore_result=True)
def sweep_subscriptions() -> dict:
    now = timezone.now()

    entered_grace = 0
    for subscription in Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE, current_period_end__lte=now
    ):
        try:
            enter_grace_period(subscription=subscription)
            entered_grace += 1
        except Exception:
            logger.exception("Failed to move subscription %s into its grace period", subscription.public_id)

    suspended = 0
    for subscription in Subscription.objects.filter(
        status=SubscriptionStatus.GRACE_PERIOD, grace_period_ends_at__lte=now
    ):
        try:
            suspend(subscription=subscription, actor_type=Actor.SYSTEM, reason="Grace period ended unpaid")
            suspended += 1
        except Exception:
            logger.exception("Failed to suspend subscription %s", subscription.public_id)

    reminders_sent = _send_renewal_reminders(now)

    return {"entered_grace": entered_grace, "suspended": suspended, "reminders_sent": reminders_sent}


def _send_renewal_reminders(now) -> int:
    """One reminder per newly-crossed threshold, most-distant first (`RENEWAL_REMINDER_DAYS`
    is descending) — `last_reminder_days` is the dedupe key so a threshold never fires twice."""
    sent = 0
    candidates = Subscription.objects.filter(
        status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE_PERIOD)
    ).select_related("bot", "bot__tenant")

    for subscription in candidates:
        days_left = (subscription.current_period_end - now).days
        for lead in RENEWAL_REMINDER_DAYS:
            already_sent = (
                subscription.last_reminder_days is not None
                and subscription.last_reminder_days <= lead
            )
            if days_left > lead or already_sent:
                continue
            Subscription.objects.filter(pk=subscription.pk).update(last_reminder_days=lead)
            publish(
                "subscription.renewal_due",
                {
                    "tenant_id": str(subscription.bot.tenant.public_id),
                    "bot_id": str(subscription.bot.public_id),
                    "dedupe_key": f"subscription_renewal:{subscription.public_id}:{lead}",
                    "days_left": max(days_left, 0),
                },
            )
            sent += 1
            break
    return sent
