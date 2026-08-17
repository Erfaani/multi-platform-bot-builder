"""Core background tasks.

Celery delivers at least once, so every task here is idempotent by key.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.core.models import IdempotencyRecord, OutboxMessage

logger = logging.getLogger(__name__)

MAX_RELAY_ATTEMPTS = 10

#: apps/core/tasks.py — see CELERY_BEAT_SCHEDULE.
SWEEP_INTERVAL_SECONDS = 300
PURGE_INTERVAL_SECONDS = 21600


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def relay_outbox_message(self, message_pk: int) -> str:
    """Publish one outbox message to its consumers.

    Consumers are registered in later phases (notifications, analytics). Until then
    this marks the message published so the backlog does not grow unbounded.
    """
    with transaction.atomic():
        message = (
            OutboxMessage.objects.select_for_update(skip_locked=True)
            .filter(pk=message_pk, status=OutboxMessage.Status.PENDING)
            .first()
        )
        if message is None:
            return "skipped"  # already published, or claimed by another worker

        try:
            _dispatch(message)
        except Exception as exc:
            message.attempts += 1
            message.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            if message.attempts >= MAX_RELAY_ATTEMPTS:
                message.status = OutboxMessage.Status.FAILED
                logger.error("Outbox message %s failed permanently", message.public_id)
            message.save(update_fields=["attempts", "last_error", "status", "published_at"])
            raise self.retry(exc=exc) from exc

        message.status = OutboxMessage.Status.PUBLISHED
        message.published_at = timezone.now()
        message.save(update_fields=["status", "published_at"])
    return "published"


def _dispatch(message: OutboxMessage) -> None:
    """Fan a domain event out to its consumers.

    Consumers must be idempotent: the relay is at-least-once, so a retry after a
    partial failure will call them again with the same event.
    """
    logger.info("Domain event %s (%s)", message.event_type, message.public_id)

    from apps.notifications.services import notify_from_event

    notify_from_event(message.event_type, message.payload)

    # An approved payment starts provisioning. Routed through the outbox rather than
    # called from `approve_payment` directly, so a provisioning hiccup can never roll
    # back an approval that the customer has already been told about.
    if message.event_type == "order.paid":
        order_id = message.payload.get("order_id")
        if order_id:
            transaction.on_commit(lambda: _enqueue_provisioning(order_id))


def _enqueue_provisioning(order_public_id: str) -> None:
    from apps.provisioning.tasks import provision_order

    try:
        provision_order.delay(order_public_id)
    except Exception:
        logger.warning(
            "Could not enqueue provisioning for order %s; it can be retried from the admin.",
            order_public_id,
            exc_info=True,
        )


@shared_task
def sweep_pending_outbox(limit: int = 500) -> int:
    """Safety net for events whose on_commit hook never ran (process died).

    Scheduled periodically; the relay task itself is the fast path.
    """
    pending = OutboxMessage.objects.filter(status=OutboxMessage.Status.PENDING).values_list(
        "pk", flat=True
    )[:limit]
    count = 0
    for pk in pending:
        relay_outbox_message.delay(pk)
        count += 1
    return count


@shared_task
def purge_expired_idempotency_records() -> int:
    deleted, _ = IdempotencyRecord.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted
