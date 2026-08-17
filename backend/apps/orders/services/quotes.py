"""Quote use cases.

The single rule this file exists to enforce: **the server prices the quote**. The client
sends a configuration; it never sends an amount. Everything a customer will be billed
is computed here from the live price list and frozen into `QuoteItem` rows.
"""

from __future__ import annotations

import hmac
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.business_templates.models import BusinessTemplate
from apps.core.errors import ConflictError, NotFoundError, ValidationError
from apps.features.registry import all_manifests, resolve_dependencies
from apps.features.services import unavailable_selections
from apps.orders.models import QUOTE_TTL, Quote, QuoteItem, QuoteSource
from apps.pricing.domain import PriceNotFound, calculate_addon_quote, calculate_quote
from apps.pricing.services import live_prices, resolve_price_list
from apps.platforms.constants import SELLABLE_PLATFORMS


def _validate_platforms(platforms: list[str]) -> list[str]:
    if not platforms:
        raise ValidationError(
            code="quote.no_platform",
            field_errors={"platforms": ["Choose at least one platform."]},
        )
    unknown = [p for p in platforms if p not in SELLABLE_PLATFORMS]
    if unknown:
        raise ValidationError(
            code="quote.unknown_platform",
            field_errors={"platforms": [f"Not available: {', '.join(unknown)}."]},
        )
    return sorted(set(platforms))


def _validate_features(
    template: BusinessTemplate, selected: list[str], platforms: list[str]
) -> tuple[list[str], list[str]]:
    registry = all_manifests()

    unknown = [slug for slug in selected if slug not in registry]
    if unknown:
        raise ValidationError(
            code="quote.unknown_feature",
            field_errors={"features": [f"Unknown features: {', '.join(unknown)}."]},
        )

    offered = set(
        template.template_features.filter(feature__is_active=True).values_list(
            "feature__slug", flat=True
        )
    )
    not_offered = [slug for slug in selected if slug not in offered]
    if not_offered:
        raise ValidationError(
            code="quote.feature_not_in_template",
            field_errors={
                "features": [
                    f"This template does not offer: {', '.join(not_offered)}."
                ]
            },
        )

    # Required features are added back even if the client omitted them.
    wanted = list(dict.fromkeys([*template.required_feature_slugs(), *selected]))
    resolved, auto_added = resolve_dependencies(wanted)

    problems = unavailable_selections(resolved, platforms)
    if problems:
        raise ValidationError(
            code="quote.feature_unavailable_on_platform",
            message="Some selected features are not available on the chosen platforms.",
            details={
                "conflicts": [
                    {
                        "feature": p.feature_slug,
                        "platform": p.platform,
                        "reason": p.reason,
                        "note": p.note,
                    }
                    for p in problems
                ]
            },
        )

    return resolved, auto_added


@transaction.atomic
def build_quote(
    *,
    template_slug: str,
    platforms: list[str],
    feature_slugs: list[str],
    currency: str | None = None,
    country: str = "",
    locale: str = "en",
    business_draft: dict[str, Any] | None = None,
    created_via: str = QuoteSource.WEB,
    user=None,
    quote: Quote | None = None,
) -> tuple[Quote, list[str]]:
    """Price a configuration, creating or re-pricing a quote.

    Returns ``(quote, auto_added_feature_slugs)`` so the builder can explain why FAQ
    appeared when the customer picked the AI assistant.
    """
    template = BusinessTemplate.objects.filter(slug=template_slug, is_active=True).first()
    if template is None:
        raise NotFoundError(code="quote.unknown_template", message="Unknown business template.")

    platforms = _validate_platforms(platforms)
    resolved, auto_added = _validate_features(template, feature_slugs, platforms)

    price_list = resolve_price_list(currency=currency, country=country)
    prices = live_prices(price_list)

    try:
        totals = calculate_quote(
            currency=price_list.currency,
            template_slug=template.slug,
            platforms=platforms,
            feature_slugs=resolved,
            prices=prices,
        )
    except PriceNotFound as exc:
        # Refusing to quote is the correct behaviour: a total computed from an
        # incomplete price list would under-charge silently.
        raise ConflictError(code="pricing.incomplete", message=str(exc)) from exc

    if quote is None:
        quote = Quote(template=template, price_list=price_list, currency=price_list.currency)
    elif quote.is_claimed and user is not None and quote.tenant_id is not None:
        pass  # re-pricing a claimed quote is fine; ownership does not change

    quote.template = template
    quote.price_list = price_list
    quote.currency = price_list.currency
    quote.platforms = platforms
    quote.selected_features = list(feature_slugs)
    quote.resolved_features = resolved
    quote.business_draft = business_draft if business_draft is not None else quote.business_draft
    quote.locale = locale
    quote.created_via = created_via
    if user is not None and getattr(user, "pk", None) and quote.created_by_id is None:
        quote.created_by = user

    quote.subtotal_once_minor = totals.one_time.amount_minor
    quote.subtotal_recurring_minor = totals.recurring_monthly.amount_minor
    quote.total_minor = totals.subtotal.amount_minor - quote.discount_minor + quote.tax_minor
    quote.expires_at = timezone.now() + QUOTE_TTL
    quote.save()

    # Re-priced from scratch: stale lines must never survive a configuration change.
    quote.items.all().delete()
    QuoteItem.objects.bulk_create(
        [
            QuoteItem(
                quote=quote,
                price_key=item.price_key,
                label_key=item.label_key,
                feature_slug=item.feature_slug or "",
                price_version_id=prices[item.price_key].price_version_id,
                unit_amount_minor=item.unit_amount.amount_minor,
                quantity=item.quantity,
                amount_minor=item.amount.amount_minor,
                currency=quote.currency,
                billing_kind=item.billing_kind,
                sort_order=index * 10,
            )
            for index, item in enumerate(totals.items)
        ]
    )

    return quote, auto_added


def _validate_addon_features(bot, feature_slugs: list[str]) -> tuple[list[str], list[str]]:
    """Like `_validate_features`, minus the anonymous-builder concerns: no template
    "required features" backfill (the bot already has those), and dependencies already
    owned are not re-sold.
    """
    registry = all_manifests()

    unknown = [slug for slug in feature_slugs if slug not in registry]
    if unknown:
        raise ValidationError(
            code="quote.unknown_feature",
            field_errors={"features": [f"Unknown features: {', '.join(unknown)}."]},
        )

    owned = set(
        bot.bot_features.filter(is_enabled=True).values_list("feature__slug", flat=True)
    )
    already_owned = [slug for slug in feature_slugs if slug in owned]
    if already_owned:
        raise ConflictError(
            code="quote.feature_already_enabled",
            message=f"Already enabled: {', '.join(already_owned)}.",
        )

    offered = set(
        bot.template.template_features.filter(feature__is_active=True).values_list(
            "feature__slug", flat=True
        )
    )
    not_offered = [slug for slug in feature_slugs if slug not in offered]
    if not_offered:
        raise ValidationError(
            code="quote.feature_not_in_template",
            field_errors={
                "features": [f"This bot's template does not offer: {', '.join(not_offered)}."]
            },
        )

    resolved, added = resolve_dependencies(feature_slugs)
    # Dependencies the bot already owns are not being bought again.
    to_buy = [slug for slug in resolved if slug not in owned]
    auto_added = [slug for slug in added if slug not in owned]

    platforms = list(bot.instances.values_list("platform", flat=True))
    problems = unavailable_selections(to_buy, platforms)
    if problems:
        raise ValidationError(
            code="quote.feature_unavailable_on_platform",
            message="Some selected features are not available on this bot's platforms.",
            details={
                "conflicts": [
                    {
                        "feature": p.feature_slug,
                        "platform": p.platform,
                        "reason": p.reason,
                        "note": p.note,
                    }
                    for p in problems
                ]
            },
        )

    return to_buy, auto_added


@transaction.atomic
def build_addon_quote(
    *, bot, feature_slugs: list[str], user, locale: str = "en"
) -> tuple[Quote, list[str]]:
    """Price additional features for a bot that is already live (spec §24).

    Unlike the builder's `build_quote`, this quote is never anonymous — the bot already
    belongs to a tenant, so it is created pre-claimed and skips straight to being
    orderable. Nothing here re-prices the template, platform or hosting: the customer
    already paid for those (`pricing.domain.calculate_addon_quote`).
    """
    to_buy, auto_added = _validate_addon_features(bot, feature_slugs)

    price_list = resolve_price_list(currency=bot.currency, country=bot.tenant.country)
    prices = live_prices(price_list)

    try:
        totals = calculate_addon_quote(currency=price_list.currency, feature_slugs=to_buy, prices=prices)
    except PriceNotFound as exc:
        raise ConflictError(code="pricing.incomplete", message=str(exc)) from exc

    quote = Quote.objects.create(
        tenant=bot.tenant,
        created_by=user if getattr(user, "pk", None) else None,
        created_via=QuoteSource.WEB,
        template=bot.template,
        target_bot=bot,
        platforms=list(bot.instances.values_list("platform", flat=True)),
        selected_features=list(feature_slugs),
        resolved_features=to_buy,
        business_draft={},
        locale=locale,
        currency=price_list.currency,
        price_list=price_list,
        subtotal_once_minor=totals.one_time.amount_minor,
        subtotal_recurring_minor=totals.recurring_monthly.amount_minor,
        total_minor=totals.subtotal.amount_minor,
        expires_at=timezone.now() + QUOTE_TTL,
    )

    QuoteItem.objects.bulk_create(
        [
            QuoteItem(
                quote=quote,
                price_key=item.price_key,
                label_key=item.label_key,
                feature_slug=item.feature_slug or "",
                price_version_id=prices[item.price_key].price_version_id,
                unit_amount_minor=item.unit_amount.amount_minor,
                quantity=item.quantity,
                amount_minor=item.amount.amount_minor,
                currency=quote.currency,
                billing_kind=item.billing_kind,
                sort_order=index * 10,
            )
            for index, item in enumerate(totals.items)
        ]
    )

    record_audit(
        actor=user,
        action="quote.addon_built",
        resource_type="quote",
        resource_id=str(quote.public_id),
        tenant=bot.tenant,
        metadata={"bot": str(bot.public_id), "features": to_buy},
    )
    return quote, auto_added


def get_quote_for_request(*, public_id: str, session_secret: str = "", user=None) -> Quote:
    """Fetch a quote the caller is entitled to see.

    Either they hold the session secret (anonymous builder) or they belong to the tenant
    that claimed it. A bare `public_id` is never enough for a claimed quote.
    """
    quote = Quote.objects.filter(public_id=public_id).select_related("template").first()
    if quote is None:
        raise NotFoundError()

    if quote.tenant_id is None:
        if session_secret and hmac.compare_digest(quote.session_secret, session_secret):
            return quote
        raise NotFoundError()

    if user is not None and getattr(user, "is_authenticated", False):
        from apps.customers.models import TenantMembership

        if TenantMembership.objects.filter(tenant_id=quote.tenant_id, user=user).exists():
            return quote

    raise NotFoundError()


@transaction.atomic
def claim_quote(*, quote: Quote, tenant, user) -> Quote:
    """Bind an anonymous quote to a tenant. One-way and final."""
    if quote.tenant_id is not None:
        if quote.tenant_id == tenant.pk:
            return quote
        raise ConflictError(
            code="quote.already_claimed",
            message="This quote already belongs to another workspace.",
        )

    if quote.is_expired:
        raise ConflictError(
            code="quote.expired", message="This quote has expired. Please rebuild it."
        )

    quote.tenant = tenant
    if quote.created_by_id is None and getattr(user, "pk", None):
        quote.created_by = user
    quote.save(update_fields=["tenant", "created_by", "updated_at"])

    record_audit(
        actor=user,
        action="quote.claimed",
        resource_type="quote",
        resource_id=str(quote.public_id),
        tenant=tenant,
    )
    return quote
