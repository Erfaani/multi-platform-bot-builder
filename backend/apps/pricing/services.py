"""Pricing services: reading live prices, and changing them safely."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.core.errors import NotFoundError, ValidationError
from apps.pricing.domain import PriceEntry
from apps.pricing.models import BillingKind, PriceList, PriceVersion


def resolve_price_list(*, currency: str | None = None, country: str = "") -> PriceList:
    """Pick the price list for a customer.

    Currency is the strong signal; country only narrows between lists sharing one.
    """
    lists = PriceList.objects.filter(is_active=True)

    if currency:
        candidates = list(lists.filter(currency=currency.upper()))
        if not candidates:
            raise NotFoundError(
                code="pricing.no_price_list",
                message="We do not yet sell in this currency.",
            )
        if country:
            scoped = [pl for pl in candidates if country.upper() in (pl.country_scope or [])]
            if scoped:
                return scoped[0]
        default = [pl for pl in candidates if pl.is_default]
        return default[0] if default else candidates[0]

    if country:
        scoped = [pl for pl in lists if country.upper() in (pl.country_scope or [])]
        if scoped:
            return scoped[0]

    fallback = lists.filter(is_default=True).first() or lists.first()
    if fallback is None:
        raise NotFoundError(code="pricing.no_price_list", message="Pricing is not configured.")
    return fallback


def live_prices(price_list: PriceList) -> dict[str, PriceEntry]:
    """Every live price on a list, keyed by price key."""
    return {
        version.price_key: PriceEntry(
            amount_minor=version.amount_minor,
            billing_kind=version.billing_kind,
            price_version_id=version.pk,
        )
        for version in PriceVersion.objects.live().filter(price_list=price_list)
    }


@transaction.atomic
def set_price(
    *,
    price_list: PriceList,
    price_key: str,
    amount_minor: int,
    billing_kind: str = BillingKind.ONE_TIME,
    actor=None,
    note: str = "",
) -> PriceVersion:
    """Change a price by closing the current version and inserting a new one.

    Never an UPDATE. Existing orders reference the closed row and keep the amount they
    were sold at (spec §12).
    """
    if amount_minor < 0:
        raise ValidationError(
            code="pricing.negative_amount",
            field_errors={"amount_minor": ["A price cannot be negative."]},
        )

    now = timezone.now()
    current = (
        PriceVersion.objects.select_for_update()
        .live()
        .filter(price_list=price_list, price_key=price_key)
        .first()
    )

    if current is not None:
        if current.amount_minor == amount_minor and current.billing_kind == billing_kind:
            return current  # idempotent: seeding repeatedly must not churn history
        current.valid_to = now
        current.save(update_fields=["valid_to", "updated_at"])

    version = PriceVersion.objects.create(
        price_list=price_list,
        price_key=price_key,
        amount_minor=amount_minor,
        billing_kind=billing_kind,
        created_by=actor if getattr(actor, "pk", None) else None,
        note=note,
    )

    record_audit(
        actor=actor,
        action="pricing.price_changed",
        resource_type="price_version",
        resource_id=str(version.pk),
        metadata={
            "price_list": price_list.slug,
            "price_key": price_key,
            "from_minor": current.amount_minor if current else None,
            "to_minor": amount_minor,
        },
    )
    return version


def price_history(price_list: PriceList, price_key: str) -> list[PriceVersion]:
    """Newest first.

    Tie-broken by id: two changes within the same clock tick share a `valid_from`, and
    an audit trail that reorders itself between reads is not an audit trail.
    """
    return list(
        PriceVersion.objects.filter(price_list=price_list, price_key=price_key).order_by(
            "-valid_from", "-id"
        )
    )
