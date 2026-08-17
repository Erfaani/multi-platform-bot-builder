"""Quote calculation — pure domain logic.

No ORM, no settings, no I/O: prices come in as a plain mapping so the whole pricing
policy can be unit-tested exhaustively without a database. This is the file to read to
understand what a customer is actually charged.

Platform pricing follows spec §9 literally:

    Telegram          → base
    Bale              → base
    Telegram + Bale   → base + multi-platform fee

so the shared business configuration is paid for **once**, and each additional channel
adds a surcharge rather than a second full price. Multiplying by the number of channels
would charge twice for work done once, which the spec explicitly rules out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.core.money import Money, sum_money

MULTI_PLATFORM_SURCHARGE_KEY = "platform.multi.surcharge"
HOSTING_KEY = "hosting.standard.monthly"


class PriceNotFound(LookupError):
    """A required price key is missing from the price list."""


@dataclass(frozen=True, slots=True)
class PricedItem:
    price_key: str
    label_key: str
    unit_amount: Money
    quantity: int
    billing_kind: str
    feature_slug: str | None = None

    @property
    def amount(self) -> Money:
        return self.unit_amount * self.quantity


@dataclass(frozen=True, slots=True)
class QuoteTotals:
    currency: str
    items: list[PricedItem] = field(default_factory=list)

    @property
    def one_time(self) -> Money:
        return sum_money(
            [item.amount for item in self.items if item.billing_kind == "ONE_TIME"],
            self.currency,
        )

    @property
    def recurring_monthly(self) -> Money:
        return sum_money(
            [item.amount for item in self.items if item.billing_kind == "RECURRING_MONTHLY"],
            self.currency,
        )

    @property
    def subtotal(self) -> Money:
        """What the customer pays now: setup plus the first recurring period."""
        return self.one_time + self.recurring_monthly


@dataclass(frozen=True, slots=True)
class PriceEntry:
    amount_minor: int
    billing_kind: str
    price_version_id: int | None = None


def _require(prices: dict[str, PriceEntry], key: str) -> PriceEntry:
    try:
        return prices[key]
    except KeyError as exc:
        raise PriceNotFound(
            f"No live price for {key!r}. A quote cannot be produced with an incomplete "
            "price list — showing a wrong total is worse than refusing to quote."
        ) from exc


def _item(
    prices: dict[str, PriceEntry],
    currency: str,
    key: str,
    label_key: str,
    *,
    quantity: int = 1,
    feature_slug: str | None = None,
    optional: bool = False,
) -> PricedItem | None:
    entry = prices.get(key) if optional else _require(prices, key)
    if entry is None:
        return None
    return PricedItem(
        price_key=key,
        label_key=label_key,
        unit_amount=Money(entry.amount_minor, currency),
        quantity=quantity,
        billing_kind=entry.billing_kind,
        feature_slug=feature_slug,
    )


def _feature_items(
    prices: dict[str, PriceEntry], currency: str, feature_slugs: list[str]
) -> list[PricedItem]:
    """Priced setup/monthly lines for a set of features.

    Shared by `calculate_quote` and `calculate_addon_quote` — features are priced once
    each regardless of which of the two produced the quote, because the same
    configuration drives every channel (spec §61.1).
    """
    items: list[PricedItem] = []
    for slug in feature_slugs:
        for suffix in ("setup", "monthly"):
            item = _item(
                prices,
                currency,
                f"feature.{slug}.{suffix}",
                f"pricing.feature.{slug}.{suffix}",
                feature_slug=slug,
                optional=True,  # not every feature has both a setup and a monthly price
            )
            if item is not None and item.unit_amount.amount_minor != 0:
                items.append(item)
    return items


def calculate_quote(
    *,
    currency: str,
    template_slug: str,
    platforms: list[str],
    feature_slugs: list[str],
    prices: dict[str, PriceEntry],
    include_hosting: bool = True,
) -> QuoteTotals:
    """Price a bot configuration.

    ``platforms`` must be de-duplicated and non-empty; the caller validates that.
    """
    if not platforms:
        raise ValueError("At least one platform is required to price a bot.")

    ordered_platforms = sorted(set(platforms))
    items: list[PricedItem] = []

    # 1. Shared configuration for the vertical — charged once, whatever the channels.
    items.append(
        _item(
            prices,
            currency,
            f"template.{template_slug}.base",
            f"pricing.template.{template_slug}",
        )
    )

    # 2. The primary channel. Deterministically the most expensive one, so the total
    #    does not depend on the order the customer happened to tick the boxes.
    platform_keys = {p: f"platform.{p}.base" for p in ordered_platforms}
    for key in platform_keys.values():
        _require(prices, key)

    primary = max(
        ordered_platforms,
        key=lambda p: (prices[platform_keys[p]].amount_minor, p),
    )
    items.append(
        _item(prices, currency, platform_keys[primary], f"pricing.platform.{primary}")
    )

    # 3. Each additional channel is a surcharge, not another full price.
    additional = len(ordered_platforms) - 1
    if additional > 0:
        items.append(
            _item(
                prices,
                currency,
                MULTI_PLATFORM_SURCHARGE_KEY,
                "pricing.platform.multi",
                quantity=additional,
            )
        )

    # 4. Features. Priced once each — the same configuration drives every channel,
    #    so charging per platform would bill twice for one piece of work (spec §61.1).
    items.extend(_feature_items(prices, currency, feature_slugs))

    # 5. Hosting, which is what makes "no server required" possible.
    if include_hosting:
        hosting = _item(prices, currency, HOSTING_KEY, "pricing.hosting", optional=True)
        if hosting is not None:
            items.append(hosting)

    return QuoteTotals(currency=currency, items=[i for i in items if i is not None])


def calculate_addon_quote(
    *, currency: str, feature_slugs: list[str], prices: dict[str, PriceEntry]
) -> QuoteTotals:
    """Price *additional* features for a bot that is already live (spec §24).

    Deliberately excludes the template base, platform base/surcharge and hosting — the
    customer already paid for the shared configuration and the channel; charging those
    again on every add-on would double-bill for work that was done once.
    """
    if not feature_slugs:
        raise ValueError("At least one feature is required to price an add-on.")

    items = _feature_items(prices, currency, feature_slugs)
    return QuoteTotals(currency=currency, items=items)
