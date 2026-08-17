"""Recording and summarising bot activity.

`record_event` is called from the dispatcher's hot path, so it must be cheap and must
never be able to break a reply — a failure here is logged and swallowed, the same
contract the outbox relay holds itself to (docs/01-ARCHITECTURE-REVIEW.md F-11).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.analytics.models import AnalyticsEvent, EventType

logger = logging.getLogger(__name__)

SUMMARY_WINDOW_DAYS = 14


def record_event(
    *, tenant_id: int, bot_id: int, event_type: str, label: str = "", contact_id: int | None = None
) -> None:
    try:
        AnalyticsEvent.objects.create(
            tenant_id=tenant_id,
            bot_id=bot_id,
            contact_id=contact_id,
            event_type=event_type,
            label=label[:64],
            occurred_at=timezone.now(),
        )
    except Exception:
        # Analytics must never be the reason a customer's message goes unanswered.
        logger.warning("Failed to record analytics event %s for bot %s", event_type, bot_id, exc_info=True)


def bot_summary(bot) -> dict:
    """Stat tiles plus a small daily series for the dashboard (spec §31)."""
    from apps.bot_runtime.models import BusinessContact

    now = timezone.now()
    since_7d = now - timedelta(days=7)
    since_window = now - timedelta(days=SUMMARY_WINDOW_DAYS)

    total_contacts = BusinessContact.objects.filter(bot=bot).count()
    new_contacts_7d = BusinessContact.objects.filter(bot=bot, first_seen_at__gte=since_7d).count()
    messages_7d = AnalyticsEvent.objects.filter(
        bot=bot, event_type=EventType.MESSAGE_RECEIVED, occurred_at__gte=since_7d
    ).count()

    daily = (
        AnalyticsEvent.objects.filter(
            bot=bot, event_type=EventType.MESSAGE_RECEIVED, occurred_at__gte=since_window
        )
        .annotate(day=TruncDate("occurred_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    series = {row["day"].isoformat(): row["count"] for row in daily}

    # Fill in zero-message days so the sparkline has one point per day, not gaps.
    points = []
    for offset in range(SUMMARY_WINDOW_DAYS - 1, -1, -1):
        day = (now - timedelta(days=offset)).date()
        points.append({"date": day.isoformat(), "count": series.get(day.isoformat(), 0)})

    return {
        "total_contacts": total_contacts,
        "new_contacts_7d": new_contacts_7d,
        "messages_7d": messages_7d,
        "daily_messages": points,
    }
