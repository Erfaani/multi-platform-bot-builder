"""Subscription lifecycle: starting, renewing, and — the point of this phase — expiring.

`transition_order()` (Phase 3) already knows how to move `Order.status` through
`ACTIVE → GRACE_PERIOD → SUSPENDED → ACTIVE` and publishes `order.{status}` on every
move, which is what already-wired notifications (`order.suspended`, `order.active`,
Phase 3) and the order's own audit trail (`OrderEvent`) run on. Nothing here duplicates
that — every function below moves the `Subscription` row (the thing this phase actually
adds) and, in the same transaction, mirrors the move onto the order for free history and
notifications. Only `Bot.status` / `BotPlatformInstance.status` — flipped here too — is
what the runtime actually checks (`apps.bot_runtime.context.load_instance`) before
answering a webhook, which is what "the bot actually stops responding" means in practice.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.services import record_audit
from apps.bots import credentials as credential_service
from apps.bots.models import Bot, BotPlatformInstance, BotStatus
from apps.core.events import publish
from apps.orders.domain import state_machine
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.services import transition_order
from apps.provisioning.provisioners import get_provisioner
from apps.provisioning.saga import rotate_webhook_secret, webhook_url_for

from apps.subscriptions.models import Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)

#: A fixed 30-day cycle, not calendar-month-exact — simple, deterministic, and matches
#: `BillingKind.RECURRING_MONTHLY` (Phase 2) closely enough for a manually-billed SaaS
#: with no live payment gateway to reconcile against a real calendar billing date.
BILLING_PERIOD = dt.timedelta(days=30)
#: How long a bot keeps working after its period lapses, before it is actually suspended.
GRACE_PERIOD = dt.timedelta(days=7)
#: Renewal reminders fire once each, in descending order, as the period end is crossed.
RENEWAL_REMINDER_DAYS: tuple[int, ...] = (7, 3, 1)


def get_for_bot(bot: Bot) -> Subscription | None:
    return Subscription.objects.filter(bot=bot).first()


@transaction.atomic
def start(*, bot: Bot, order) -> Subscription:
    """Create the subscription when a bot first goes live (`provisioning.saga.step_activate`)."""
    subscription, _created = Subscription.objects.get_or_create(
        bot=bot,
        defaults={
            "tenant": bot.tenant,
            "monthly_amount_minor": order.subtotal_recurring_minor,
            "currency": order.currency,
            "current_period_end": timezone.now() + BILLING_PERIOD,
        },
    )
    return subscription


@transaction.atomic
def add_recurring_amount(*, bot: Bot, order) -> Subscription | None:
    """An add-on order added its own recurring items — fold them into the same bill."""
    subscription = get_for_bot(bot)
    if subscription is None or order.subtotal_recurring_minor == 0:
        return subscription

    Subscription.objects.filter(pk=subscription.pk).update(
        monthly_amount_minor=F("monthly_amount_minor") + order.subtotal_recurring_minor
    )
    subscription.refresh_from_db(fields=["monthly_amount_minor"])
    return subscription


def _mirror_to_order(bot: Bot, target: OrderStatus, *, actor_type: Actor, user=None, reason: str) -> None:
    """Move `bot.origin_order` alongside the subscription, for the audit trail and the
    notification catalogue — tolerating an order that is not where we expect (e.g.
    already cancelled) rather than blocking the subscription's own state change on it."""
    if not bot.origin_order_id:
        return
    source = OrderStatus(bot.origin_order.status)
    if state_machine.find(source, target) is None:
        return
    transition_order(order=bot.origin_order, target=target, actor_type=actor_type, user=user, reason=reason)


@transaction.atomic
def enter_grace_period(*, subscription: Subscription) -> Subscription:
    """The billing period lapsed unpaid. SYSTEM-only — driven by `tasks.sweep_subscriptions`."""
    locked = Subscription.objects.select_for_update().get(pk=subscription.pk)
    if locked.status != SubscriptionStatus.ACTIVE:
        return locked  # idempotent — a retried sweep must not double-fire the notification

    bot = Bot.objects.select_related("tenant", "origin_order").get(pk=locked.bot_id)
    locked.status = SubscriptionStatus.GRACE_PERIOD
    locked.grace_period_ends_at = timezone.now() + GRACE_PERIOD
    locked.last_reminder_days = None
    locked.save(update_fields=["status", "grace_period_ends_at", "last_reminder_days", "updated_at"])

    _mirror_to_order(
        bot, OrderStatus.GRACE_PERIOD, actor_type=Actor.SYSTEM, reason="Billing period ended unpaid"
    )
    publish(
        "subscription.grace_period",
        {
            "tenant_id": str(bot.tenant.public_id),
            "bot_id": str(bot.public_id),
            "dedupe_key": f"subscription_grace:{locked.public_id}:{locked.grace_period_ends_at.date().isoformat()}",
            "grace_period_ends_at": locked.grace_period_ends_at.isoformat(),
        },
    )
    record_audit(
        actor=None, action="subscription.grace_period_started", resource_type="subscription",
        resource_id=str(locked.public_id), tenant=bot.tenant,
    )
    return locked


@transaction.atomic
def suspend(
    *, subscription: Subscription, actor_type: Actor = Actor.SYSTEM, user=None, reason: str = ""
) -> Subscription:
    """Disable the runtime for real: flip every instance, remove its webhook, flip the bot."""
    locked = Subscription.objects.select_for_update().get(pk=subscription.pk)
    if locked.status == SubscriptionStatus.SUSPENDED:
        return locked  # idempotent

    bot = Bot.objects.select_related("tenant", "origin_order").get(pk=locked.bot_id)

    for instance in BotPlatformInstance.objects.filter(bot=bot).exclude(
        status=BotPlatformInstance.Status.SUSPENDED
    ):
        provisioner = get_provisioner(instance.platform)
        if provisioner is not None and instance.webhook_set_at:
            try:
                token = credential_service.read_token(instance=instance, purpose="delete_webhook")
                provisioner.delete_webhook(token)
            except Exception:
                # The instance is marked SUSPENDED regardless (below) — `load_instance`'s
                # status filter is what actually stops traffic; a webhook the platform
                # keeps calling into a suspended instance is wasted, not unsafe.
                logger.exception(
                    "Failed to remove the webhook for instance %s while suspending", instance.public_id
                )
        instance.status = BotPlatformInstance.Status.SUSPENDED
        instance.save(update_fields=["status", "updated_at"])

    bot.status = BotStatus.SUSPENDED
    bot.save(update_fields=["status", "updated_at"])

    locked.status = SubscriptionStatus.SUSPENDED
    locked.suspended_at = timezone.now()
    locked.grace_period_ends_at = None
    locked.save(update_fields=["status", "suspended_at", "grace_period_ends_at", "updated_at"])

    _mirror_to_order(bot, OrderStatus.SUSPENDED, actor_type=actor_type, user=user, reason=reason or "Subscription suspended")
    record_audit(
        actor=user, action="subscription.suspended", resource_type="subscription",
        resource_id=str(locked.public_id), tenant=bot.tenant, metadata={"reason": reason},
    )
    return locked


def _reactivate_runtime(bot: Bot) -> None:
    for instance in BotPlatformInstance.objects.filter(bot=bot, status=BotPlatformInstance.Status.SUSPENDED):
        provisioner = get_provisioner(instance.platform)
        if provisioner is None:
            continue
        try:
            secret = rotate_webhook_secret(instance)
            url = webhook_url_for(instance)
            token = credential_service.read_token(instance=instance, purpose="set_webhook")
            provisioner.set_webhook(token, url, secret)
        except Exception:
            logger.exception(
                "Failed to re-register the webhook for instance %s on reactivation", instance.public_id
            )
            continue
        instance.status = BotPlatformInstance.Status.ACTIVE
        instance.webhook_url = url
        instance.webhook_set_at = timezone.now()
        instance.save(update_fields=["status", "webhook_url", "webhook_set_at", "updated_at"])

    bot.status = BotStatus.ACTIVE
    bot.save(update_fields=["status", "updated_at"])


@transaction.atomic
def renew(
    *, subscription: Subscription, actor_type: Actor = Actor.STAFF, user=None, reason: str = ""
) -> Subscription:
    """Staff confirms payment was received: extend the period and clear any lapse.

    This platform has no live payment gateway — Phase 3's manual receipt-review flow is
    the only payment path — so renewal is a deliberate staff action (Django admin, same
    manual-trust model as approving a payment), not an automatic response to a detected
    charge. See PHASES.md for the self-serve-renewal scope decision.
    """
    locked = Subscription.objects.select_for_update().get(pk=subscription.pk)
    was_suspended = locked.status == SubscriptionStatus.SUSPENDED

    now = timezone.now()
    locked.current_period_end = max(locked.current_period_end, now) + BILLING_PERIOD
    locked.status = SubscriptionStatus.ACTIVE
    locked.grace_period_ends_at = None
    locked.suspended_at = None
    locked.last_reminder_days = None
    locked.save(
        update_fields=[
            "current_period_end", "status", "grace_period_ends_at", "suspended_at",
            "last_reminder_days", "updated_at",
        ]
    )

    bot = Bot.objects.select_related("tenant", "origin_order").get(pk=locked.bot_id)
    if was_suspended:
        _reactivate_runtime(bot)

    _mirror_to_order(bot, OrderStatus.ACTIVE, actor_type=actor_type, user=user, reason=reason or "Subscription renewed")
    record_audit(
        actor=user, action="subscription.renewed", resource_type="subscription",
        resource_id=str(locked.public_id), tenant=bot.tenant, metadata={"was_suspended": was_suspended},
    )
    return locked
