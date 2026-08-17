"""Price lists and immutable price versions (spec §12, ADR-0004).

`PriceVersion` rows are **never updated**. Changing a price closes the current row and
inserts a new one, so "a feature that cost $10 last year still shows $10 on that order"
is a property of the schema rather than a rule someone has to remember.

There is no FX conversion: each currency has its own admin-maintained list, so a rate
move can never silently reprice a quote a customer is looking at.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TimeStampedModel
from apps.core.money import Money


class BillingKind(models.TextChoices):
    ONE_TIME = "ONE_TIME", _("One-time")
    RECURRING_MONTHLY = "RECURRING_MONTHLY", _("Monthly")


class PriceList(PublicIdModel, TimeStampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    currency = CurrencyCodeField()
    country_scope = models.JSONField(
        default=list,
        blank=True,
        help_text=_("ISO country codes this list applies to. Empty means any country."),
    )
    is_default = models.BooleanField(
        default=False, help_text=_("Used when no list matches the customer's country.")
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "price_list"
        ordering = ("currency", "slug")

    def __str__(self) -> str:
        return f"{self.slug} ({self.currency})"


class PriceVersionQuerySet(models.QuerySet):
    def live(self) -> "PriceVersionQuerySet":
        return self.filter(valid_to__isnull=True)


class PriceVersion(TimeStampedModel):
    """One priced line item, valid for a period. Append-only."""

    price_list = models.ForeignKey(
        PriceList, on_delete=models.PROTECT, related_name="versions"
    )
    price_key = models.CharField(
        max_length=128,
        db_index=True,
        help_text=_("e.g. feature.appointment.setup, platform.telegram.base"),
    )
    amount_minor = models.BigIntegerField()
    billing_kind = models.CharField(
        max_length=32, choices=BillingKind.choices, default=BillingKind.ONE_TIME
    )

    valid_from = models.DateTimeField(auto_now_add=True)
    valid_to = models.DateTimeField(
        null=True, blank=True, help_text=_("Null means this is the live price.")
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=255, blank=True)

    objects = PriceVersionQuerySet.as_manager()

    class Meta:
        db_table = "price_version"
        ordering = ("price_key", "-valid_from")
        constraints = [
            # Exactly one live price per key per list. Two live prices would make the
            # quote total depend on row ordering, which is how billing disputes start.
            models.UniqueConstraint(
                fields=["price_list", "price_key"],
                condition=models.Q(valid_to__isnull=True),
                name="one_live_price_per_key",
            )
        ]
        indexes = [
            models.Index(fields=["price_list", "price_key"], name="price_lookup_idx"),
        ]

    def __str__(self) -> str:
        state = "live" if self.valid_to is None else "closed"
        return f"{self.price_key}={self.amount_minor} ({state})"

    @property
    def money(self) -> Money:
        return Money(self.amount_minor, self.price_list.currency)

    @property
    def is_live(self) -> bool:
        return self.valid_to is None
