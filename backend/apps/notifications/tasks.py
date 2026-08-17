"""Notification delivery."""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db.utils import OperationalError

from apps.notifications.messages import render
from apps.notifications.models import Channel, DeliveryStatus, Notification
from apps.notifications.services import mark_delivery

logger = logging.getLogger(__name__)


@shared_task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def deliver_notification(notification_pk: int) -> str:
    """A send failure (bad address, template error, SMTP rejection) is absorbed by
    `_deliver_email` into `DeliveryStatus.FAILED` and correctly never retried — nothing
    here sweeps up a permanently-failed delivery, so retrying it would just fail the
    same way again. `autoretry_for` exists only for a transient DB blip on the
    surrounding queries/writes, which nothing else here would ever pick back up."""
    notification = (
        Notification.objects.filter(pk=notification_pk)
        .select_related("recipient")
        .prefetch_related("deliveries")
        .first()
    )
    if notification is None:
        return "missing"

    locale = getattr(notification.recipient, "preferred_locale", None) or settings.LANGUAGE_CODE

    for delivery in notification.deliveries.all():
        if delivery.status != DeliveryStatus.PENDING:
            continue

        if delivery.channel == Channel.WEB:
            # The stored row *is* the in-app notification; nothing to send.
            mark_delivery(delivery, DeliveryStatus.SENT)
            continue

        if delivery.channel == Channel.EMAIL:
            _deliver_email(notification, delivery, locale)
            continue

        # Telegram/Bale delivery needs the runtime's outbound gateway (Phase 4).
        mark_delivery(delivery, DeliveryStatus.SKIPPED, "Channel not available until Phase 4.")

    return "done"


def _deliver_email(notification, delivery, locale: str) -> None:
    recipient = notification.recipient
    if recipient is None or not recipient.email:
        mark_delivery(delivery, DeliveryStatus.SKIPPED, "No email address.")
        return

    try:
        send_mail(
            subject=render(notification.title_key, notification.params, locale),
            message=render(notification.body_key, notification.params, locale),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient.email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.warning("Email delivery failed for notification %s", notification.pk)
        mark_delivery(delivery, DeliveryStatus.FAILED, f"{type(exc).__name__}: {exc}")
        return

    mark_delivery(delivery, DeliveryStatus.SENT)
