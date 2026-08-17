"""Quotes.

A `Quote` is a priced bot configuration that has not become an order yet. It is the
**one deliberate exception** to the tenancy rule (docs/01-ARCHITECTURE-REVIEW.md F-3):
the builder must work before registration (spec §44), so a quote starts anonymous,
owned by an unguessable `public_id` plus a session secret, and is bound to a tenant only
by an explicit claim. Once bound, `tenant` is immutable and everything downstream is
tenant-owned in the normal way.

`Order` itself arrives in Phase 3, along with the state machine.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import (
    CurrencyCodeField,
    PublicIdModel,
    TenantOwnedModel,
    TimeStampedModel,
)
from apps.core.money import Money, MoneyProxy
from apps.orders.domain.state_machine import OrderStatus

#: Long enough that an abandoned builder session can be resumed the next day, short
#: enough that a price change reaches the customer within a sensible window.
QUOTE_TTL = timedelta(days=7)


def _session_secret() -> str:
    return secrets.token_urlsafe(32)


class QuoteSource(models.TextChoices):
    WEB = "WEB", _("Website")
    TELEGRAM_BUILDER = "TELEGRAM_BUILDER", _("Telegram builder bot")
    BALE_BUILDER = "BALE_BUILDER", _("Bale builder bot")


class OrderKind(models.TextChoices):
    """What an order provisions.

    Kept as data on the order — never inferred from its items — so a support agent (or
    the provisioning saga, which picks its step list from this) always has a direct
    answer to "what did this order actually do".
    """

    NEW = "NEW", _("New bot")
    ADDON = "ADDON", _("Add features to an existing bot")


class Quote(PublicIdModel, TimeStampedModel):
    # Null until claimed. Deliberately not a TenantOwnedModel — see the module docstring.
    tenant = models.ForeignKey(
        "customers.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="quotes",
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="quotes"
    )
    #: Bearer secret for the anonymous builder. Knowing the public_id is not enough.
    session_secret = models.CharField(max_length=64, default=_session_secret, editable=False)

    created_via = models.CharField(
        max_length=32, choices=QuoteSource.choices, default=QuoteSource.WEB
    )

    template = models.ForeignKey(
        "business_templates.BusinessTemplate", on_delete=models.PROTECT, related_name="quotes"
    )
    platforms = models.JSONField(default=list)
    selected_features = models.JSONField(
        default=list, help_text=_("Feature slugs the customer chose, before dependency expansion.")
    )
    resolved_features = models.JSONField(
        default=list, help_text=_("What is actually priced, after dependencies and always-on.")
    )
    business_draft = models.JSONField(
        default=dict, blank=True, help_text=_("Business details entered in the builder.")
    )

    #: Set only for an add-on quote (spec §24 "add features later"). Such a quote is
    #: never anonymous — it is created already bound to the bot's tenant, so there is no
    #: claim step. See `orders.services.build_addon_quote`.
    target_bot = models.ForeignKey(
        "bots.Bot", null=True, blank=True, on_delete=models.SET_NULL, related_name="addon_quotes"
    )

    locale = models.CharField(max_length=8, default="en")
    currency = CurrencyCodeField()
    price_list = models.ForeignKey(
        "pricing.PriceList", on_delete=models.PROTECT, related_name="quotes"
    )

    subtotal_once_minor = models.BigIntegerField(default=0)
    subtotal_recurring_minor = models.BigIntegerField(default=0)
    discount_minor = models.BigIntegerField(default=0)
    tax_minor = models.BigIntegerField(default=0)
    total_minor = models.BigIntegerField(default=0)

    subtotal_once = MoneyProxy("subtotal_once_minor", "currency")
    subtotal_recurring = MoneyProxy("subtotal_recurring_minor", "currency")
    total = MoneyProxy("total_minor", "currency")

    expires_at = models.DateTimeField()
    converted_order_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "quote"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="quote_tenant_time_idx"),
            models.Index(fields=["expires_at"], name="quote_expiry_idx"),
        ]

    def __str__(self) -> str:
        return f"Quote {self.public_id}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_claimed(self) -> bool:
        return self.tenant_id is not None

    def refresh_expiry(self) -> None:
        self.expires_at = timezone.now() + QUOTE_TTL


class Order(PublicIdModel, TenantOwnedModel):
    """A placed order. Tenant-owned from birth — unlike `Quote`, there is no
    anonymous stage: you cannot buy without an account.
    """

    #: Human-facing reference (spec §17). From a dedicated sequence, never COUNT(*).
    number = models.BigIntegerField(unique=True, editable=False)

    quote = models.ForeignKey(
        Quote, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    placed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )

    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in OrderStatus],
        default=OrderStatus.DRAFT.value,
        db_index=True,
    )

    template = models.ForeignKey(
        "business_templates.BusinessTemplate", on_delete=models.PROTECT, related_name="orders"
    )
    platforms = models.JSONField(default=list)
    features = models.JSONField(default=list)
    business_snapshot = models.JSONField(default=dict, blank=True)

    kind = models.CharField(max_length=16, choices=OrderKind.choices, default=OrderKind.NEW)
    #: Set only when `kind == ADDON`: the already-live bot this order adds features to.
    target_bot = models.ForeignKey(
        "bots.Bot", null=True, blank=True, on_delete=models.SET_NULL, related_name="addon_orders"
    )

    locale = models.CharField(max_length=8, default="en")
    created_via = models.CharField(
        max_length=32, choices=QuoteSource.choices, default=QuoteSource.WEB
    )

    #: Which ADR-0002 tier provisions this order — "pool" (instant) or "token_handoff"
    #: (custom username). Blank falls back to the platform default. Recorded so support
    #: can always answer "how did this customer get their bot".
    provisioning_strategy = models.CharField(max_length=24, blank=True)

    currency = CurrencyCodeField()
    subtotal_once_minor = models.BigIntegerField(default=0)
    subtotal_recurring_minor = models.BigIntegerField(default=0)
    discount_minor = models.BigIntegerField(default=0)
    discount_reason = models.CharField(max_length=255, blank=True)
    tax_minor = models.BigIntegerField(default=0)
    total_minor = models.BigIntegerField(default=0)

    subtotal_once = MoneyProxy("subtotal_once_minor", "currency")
    subtotal_recurring = MoneyProxy("subtotal_recurring_minor", "currency")
    total = MoneyProxy("total_minor", "currency")

    placed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "order"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["tenant", "status"], name="order_tenant_status_idx"),
            models.Index(fields=["status", "created_at"], name="order_status_time_idx"),
        ]

    def __str__(self) -> str:
        return f"Order #{self.number}"

    @property
    def is_payable(self) -> bool:
        return self.status in {
            OrderStatus.PENDING_PAYMENT.value,
            OrderStatus.PAYMENT_REJECTED.value,
        }

    @property
    def is_paid_or_beyond(self) -> bool:
        from apps.orders.domain import state_machine

        return state_machine.is_paid_or_beyond(self.status)


class OrderItem(TimeStampedModel):
    """A frozen line. Copies both the price version *and* the numbers, so history
    survives even if a price row is ever archived (spec §12).
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")

    price_key = models.CharField(max_length=128)
    label_key = models.CharField(max_length=128)
    label = models.CharField(max_length=255, blank=True)
    feature_slug = models.CharField(max_length=64, blank=True)

    price_version = models.ForeignKey(
        "pricing.PriceVersion", on_delete=models.PROTECT, related_name="order_items"
    )

    unit_amount_minor = models.BigIntegerField()
    quantity = models.PositiveIntegerField(default=1)
    amount_minor = models.BigIntegerField()
    currency = CurrencyCodeField()
    billing_kind = models.CharField(max_length=32)
    sort_order = models.PositiveSmallIntegerField(default=100)

    #: Everything known about the line at purchase time, for disputes years later.
    snapshot = models.JSONField(default=dict, blank=True)

    unit_amount = MoneyProxy("unit_amount_minor", "currency")
    amount = MoneyProxy("amount_minor", "currency")

    class Meta:
        db_table = "order_item"
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return f"{self.price_key} x{self.quantity}"


class OrderEvent(models.Model):
    """Append-only transition log. The answer to "who moved this order, and when"."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    actor_type = models.CharField(max_length=16, default="SYSTEM")
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "order_event"
        ordering = ("created_at", "id")

    def __str__(self) -> str:
        return f"{self.order_id}: {self.from_status}→{self.to_status}"


class QuoteItem(TimeStampedModel):
    """A priced line, frozen against the price version that produced it."""

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="items")

    price_key = models.CharField(max_length=128)
    label_key = models.CharField(max_length=128)
    feature_slug = models.CharField(max_length=64, blank=True)

    #: PROTECT, not CASCADE: a price version is history, and deleting it would rewrite
    #: what a customer was quoted.
    price_version = models.ForeignKey(
        "pricing.PriceVersion", on_delete=models.PROTECT, related_name="quote_items"
    )

    unit_amount_minor = models.BigIntegerField()
    quantity = models.PositiveIntegerField(default=1)
    amount_minor = models.BigIntegerField()
    currency = CurrencyCodeField()
    billing_kind = models.CharField(max_length=32)
    sort_order = models.PositiveSmallIntegerField(default=100)

    unit_amount = MoneyProxy("unit_amount_minor", "currency")
    amount = MoneyProxy("amount_minor", "currency")

    class Meta:
        db_table = "quote_item"
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return f"{self.price_key} x{self.quantity}"

    @property
    def money(self) -> Money:
        return Money(self.amount_minor, self.currency)
