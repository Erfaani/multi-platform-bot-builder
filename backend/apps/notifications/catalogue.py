"""Which domain events produce a notification, and what they say.

Data rather than branching logic, so adding an event is one entry here plus its
translation keys. Events with no entry are simply not notified — silence is the default,
so a new internal event cannot accidentally spam customers.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.notifications.models import Channel


@dataclass(frozen=True, slots=True)
class NotificationSpec:
    title_key: str
    body_key: str
    channels: tuple[str, ...] = (Channel.WEB, Channel.EMAIL)
    link_template: str = ""
    #: A bot feature slug required for this event to notify anyone, e.g. an
    #: `appointment.booked` event only reaches the owner if they bought
    #: `owner_notifications` — the SaaS-platform events above have no such gate.
    requires_feature: str | None = None


ORDER_LINK = "/orders/{order_id}"

CATALOGUE: dict[str, NotificationSpec] = {
    "order.pending_payment": NotificationSpec(
        title_key="notify.order.placed.title",
        body_key="notify.order.placed.body",
        link_template=ORDER_LINK,
    ),
    "order.receipt_submitted": NotificationSpec(
        title_key="notify.payment.submitted.title",
        body_key="notify.payment.submitted.body",
        link_template=ORDER_LINK,
    ),
    "order.payment_review": NotificationSpec(
        title_key="notify.payment.review.title",
        body_key="notify.payment.review.body",
        channels=(Channel.WEB,),
        link_template=ORDER_LINK,
    ),
    "order.paid": NotificationSpec(
        title_key="notify.payment.approved.title",
        body_key="notify.payment.approved.body",
        link_template=ORDER_LINK,
    ),
    "order.payment_rejected": NotificationSpec(
        title_key="notify.payment.rejected.title",
        body_key="notify.payment.rejected.body",
        link_template=ORDER_LINK,
    ),
    "order.provisioning": NotificationSpec(
        title_key="notify.provisioning.started.title",
        body_key="notify.provisioning.started.body",
        channels=(Channel.WEB,),
        link_template=ORDER_LINK,
    ),
    "order.active": NotificationSpec(
        title_key="notify.bot.ready.title",
        body_key="notify.bot.ready.body",
        link_template=ORDER_LINK,
    ),
    "order.failed": NotificationSpec(
        title_key="notify.provisioning.failed.title",
        body_key="notify.provisioning.failed.body",
        link_template=ORDER_LINK,
    ),
    "order.cancelled": NotificationSpec(
        title_key="notify.order.cancelled.title",
        body_key="notify.order.cancelled.body",
        channels=(Channel.WEB,),
        link_template=ORDER_LINK,
    ),
    "order.suspended": NotificationSpec(
        title_key="notify.subscription.suspended.title",
        body_key="notify.subscription.suspended.body",
        link_template=ORDER_LINK,
    ),
    # -- bot activity, gated on the `owner_notifications` feature (spec's business
    # modules) — unlike the platform events above, these are about what the customer's
    # *own* bot is doing, and only reach anyone if they paid to hear about it.
    "appointment.booked": NotificationSpec(
        title_key="notify.appointment.booked.title",
        body_key="notify.appointment.booked.body",
        channels=(Channel.WEB,),
        requires_feature="owner_notifications",
    ),
    "crm.lead_captured": NotificationSpec(
        title_key="notify.lead.captured.title",
        body_key="notify.lead.captured.body",
        channels=(Channel.WEB,),
        requires_feature="owner_notifications",
    ),
    "commerce.order_placed": NotificationSpec(
        title_key="notify.commerce_order.placed.title",
        body_key="notify.commerce_order.placed.body",
        channels=(Channel.WEB,),
        requires_feature="owner_notifications",
    ),
    # AI budget exhaustion isn't bot activity the owner opted into hearing about — it's a
    # billing-adjacent event about their own AI assistant going quiet on customers, so
    # (like the platform events above) it always reaches the owner, no feature gate.
    "ai.budget_exceeded": NotificationSpec(
        title_key="notify.ai_budget.exceeded.title",
        body_key="notify.ai_budget.exceeded.body",
        channels=(Channel.WEB,),
    ),
    # Billing events, same tier as the `order.*` events above — no feature gate. Actual
    # suspension/reactivation reuse `order.suspended`/`order.active` (already wired since
    # Phase 3, fired automatically by `transition_order`); these two are what Phase 3 had
    # no equivalent for: the grace-period warning and the renewal countdown.
    "subscription.grace_period": NotificationSpec(
        title_key="notify.subscription.grace_period.title",
        body_key="notify.subscription.grace_period.body",
    ),
    "subscription.renewal_due": NotificationSpec(
        title_key="notify.subscription.renewal_due.title",
        body_key="notify.subscription.renewal_due.body",
    ),
}


def spec_for(event_type: str) -> NotificationSpec | None:
    return CATALOGUE.get(event_type)
