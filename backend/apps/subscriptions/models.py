"""Subscription records (Phase 9).

One row per bot, tracking whether *this* billing period is paid for. It deliberately
does not duplicate what `Order`/`OrderItem`/`PriceVersion` (Phase 2/3) already know about
*what* was purchased — this platform prices per feature, à la carte, and that catalogue
already is the plan; a separate "Plan" model would just be re-describing it. What did not
exist anywhere is a record of the billing *cycle*: when the current period ends, whether a
lapsed bot is still inside its grace window, and when it was actually suspended.

`Subscription.status` is the source of truth this app's own services act on;
`Bot.origin_order`'s status is moved alongside it (via `apps.orders.services.transition_order`)
purely so the existing order-lifecycle audit trail and notification catalogue
(`order.suspended`, `order.active` — wired since Phase 3) keep working unchanged. Neither
one is what actually stops the bot from responding — that's `Bot.status` /
`BotPlatformInstance.status`, flipped by `services.suspend()`/`services.reactivate()`
alongside everything else, in the same transaction.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TenantOwnedModel
from apps.core.money import MoneyProxy


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    GRACE_PERIOD = "GRACE_PERIOD", _("Grace period")
    SUSPENDED = "SUSPENDED", _("Suspended")


class Subscription(PublicIdModel, TenantOwnedModel):
    bot = models.OneToOneField(
        "bots.Bot", on_delete=models.CASCADE, related_name="subscription"
    )
    status = models.CharField(
        max_length=16, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE
    )

    #: What renews each period. Set once at activation from the order's recurring total
    #: (`Order.subtotal_recurring_minor`) and increased when an add-on order with its own
    #: recurring items goes live — see `services.start`/`services.add_recurring_amount`.
    monthly_amount_minor = models.BigIntegerField(default=0)
    currency = CurrencyCodeField()
    monthly_amount = MoneyProxy("monthly_amount_minor", "currency")

    current_period_end = models.DateTimeField()
    #: Set when entering `GRACE_PERIOD`; cleared on renewal. Null while `ACTIVE` or once
    #: `SUSPENDED` (the grace window is over either way).
    grace_period_ends_at = models.DateTimeField(null=True, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)

    #: The last renewal-reminder lead time (days) actually sent for the *current* period,
    #: so the sweep never sends the same "3 days left" reminder twice — see
    #: `services.RENEWAL_REMINDER_DAYS`.
    last_reminder_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "subscription"
        indexes = [
            models.Index(fields=["status", "current_period_end"], name="subscription_active_sweep_idx"),
            models.Index(fields=["status", "grace_period_ends_at"], name="subscription_grace_sweep_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Subscription for bot {self.bot_id} ({self.status})"
