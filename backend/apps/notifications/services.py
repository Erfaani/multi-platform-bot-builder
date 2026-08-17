"""Notification fan-out.

Consumes domain events from the outbox. Because the outbox relay is at-least-once,
`notify_from_event` must be idempotent — it is keyed on (event_type, order, recipient).
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.notifications.catalogue import spec_for
from apps.notifications.models import (
    Channel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
)

logger = logging.getLogger(__name__)


def _bot_has_feature(bot_public_id: str, slug: str) -> bool:
    from apps.bots.models import Bot

    bot = Bot.objects.filter(public_id=bot_public_id).first()
    return bot is not None and bot.has_feature(slug)


def _recipients_for_tenant(tenant_public_id: str):
    """Owners and managers of the workspace. Staff do not need billing noise."""
    from apps.customers.models import TenantMembership, TenantRole

    return list(
        TenantMembership.objects.select_related("user", "tenant")
        .filter(
            tenant__public_id=tenant_public_id,
            role__in=[TenantRole.OWNER, TenantRole.MANAGER],
        )
    )


@transaction.atomic
def notify_from_event(event_type: str, payload: dict) -> int:
    """Create notifications for a domain event. Returns how many were created."""
    spec = spec_for(event_type)
    if spec is None:
        return 0  # not a customer-facing event

    tenant_public_id = payload.get("tenant_id")
    if not tenant_public_id:
        return 0

    if spec.requires_feature:
        bot_id = payload.get("bot_id")
        if not bot_id or not _bot_has_feature(bot_id, spec.requires_feature):
            return 0

    memberships = _recipients_for_tenant(tenant_public_id)
    if not memberships:
        return 0

    order_id = payload.get("order_id", "")
    # Falls back to `order_id` so every event published before this existed keeps
    # deduplicating exactly as it always did; new, non-order events set their own.
    dedupe_key = payload.get("dedupe_key") or order_id
    link = spec.link_template.format(**payload) if spec.link_template else ""

    params = {
        "order_number": payload.get("number", ""),
        "order_id": order_id,
        "reason": payload.get("reason", ""),
        "dedupe_key": dedupe_key,
        **{k: v for k, v in payload.items() if k not in {"tenant_id", "bot_id"}},
    }

    created = 0
    for membership in memberships:
        # Idempotency guard: the relay may deliver the same event twice.
        exists = Notification.objects.filter(
            recipient=membership.user,
            event_type=event_type,
            params__dedupe_key=dedupe_key,
        ).exists()
        if exists:
            continue

        notification = Notification.objects.create(
            recipient=membership.user,
            tenant=membership.tenant,
            event_type=event_type,
            title_key=spec.title_key,
            body_key=spec.body_key,
            params=params,
            link=link,
        )
        NotificationDelivery.objects.bulk_create(
            [
                NotificationDelivery(notification=notification, channel=channel)
                for channel in spec.channels
            ]
        )
        created += 1

        transaction.on_commit(
            lambda pk=notification.pk: _dispatch_deliveries(pk)
        )

    return created


def _dispatch_deliveries(notification_pk: int) -> None:
    from apps.notifications.tasks import deliver_notification

    deliver_notification.delay(notification_pk)


def mark_read(*, notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    return notification


def mark_all_read(user) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )


def mark_delivery(
    delivery: NotificationDelivery, status: str, error: str = ""
) -> NotificationDelivery:
    delivery.status = status
    delivery.attempts += 1
    delivery.error = error[:1000]
    if status == DeliveryStatus.SENT:
        delivery.sent_at = timezone.now()
    delivery.save(update_fields=["status", "attempts", "error", "sent_at", "updated_at"])
    return delivery


def unread_count(user) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


__all__ = [
    "notify_from_event",
    "mark_read",
    "mark_all_read",
    "mark_delivery",
    "unread_count",
    "Channel",
]
