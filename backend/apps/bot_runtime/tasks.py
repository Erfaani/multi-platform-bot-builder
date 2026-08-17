"""Runtime background tasks."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db.utils import OperationalError
from django.utils import timezone
from django_redis.exceptions import ConnectionInterrupted

from apps.bot_runtime.dispatcher import dispatch_update
from apps.bot_runtime.gateway import send_now
from apps.bot_runtime.models import InboundUpdate, OutboundMessage

logger = logging.getLogger(__name__)

#: apps/bot_runtime/tasks.py — see CELERY_BEAT_SCHEDULE.
SWEEP_INTERVAL_SECONDS = 120
RETRY_OUTBOUND_INTERVAL_SECONDS = 60
PURGE_SESSIONS_INTERVAL_SECONDS = 21600


@shared_task(
    autoretry_for=(OperationalError, ConnectionInterrupted),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def process_update(update_pk: int) -> str:
    """`dispatch_update` already absorbs every exception a *handler* raises — it resets
    the session, sends a localized apology, and marks the update `FAILED`, so none of
    that ever reaches here. What can still reach here is a transient failure in the
    surrounding I/O: the session store (Redis, via `django_redis`) or the database
    blipping mid-request. `autoretry_for` is scoped to exactly those two, so a real bug
    in a handler still surfaces immediately instead of being silently retried away."""
    update = (
        InboundUpdate.objects.select_related("instance", "instance__bot")
        .filter(pk=update_pk)
        .first()
    )
    if update is None:
        return "missing"
    if update.status != InboundUpdate.Status.PENDING:
        return "already_processed"  # at-least-once delivery; this is normal

    result = dispatch_update(update)
    return "handled" if result.handled else "ignored"


@shared_task
def sweep_pending_updates(limit: int = 500) -> int:
    """Pick up updates whose enqueue failed (a broker blip at ingress time)."""
    pending = InboundUpdate.objects.filter(status=InboundUpdate.Status.PENDING).values_list(
        "pk", "instance__platform"
    )[:limit]

    count = 0
    for pk, platform in pending:
        process_update.apply_async(args=[pk], queue=platform)
        count += 1
    return count


@shared_task
def retry_outbound(limit: int = 500) -> int:
    """Re-attempt messages deferred by rate limiting or a transient failure."""
    due = OutboundMessage.objects.filter(
        status=OutboundMessage.Status.QUEUED, next_attempt_at__lte=timezone.now()
    ).order_by("is_bulk", "next_attempt_at")[:limit]

    count = 0
    for message in due:
        send_now(message)
        count += 1
    return count


@shared_task
def purge_expired_sessions() -> int:
    from apps.bot_runtime.sessions import purge_expired

    return purge_expired()
