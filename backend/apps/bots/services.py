"""Bot use cases available to a customer."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.bots import credentials as credential_service
from apps.bots.models import Bot, BotPlatformInstance
from apps.core.errors import ConflictError, NotFoundError
from apps.platforms.transport import PlatformApiError


@transaction.atomic
def submit_customer_token(*, instance: BotPlatformInstance, token: str, user) -> BotPlatformInstance:
    """Complete the tier-B handoff (ADR-0002).

    Validated against the platform *before* it is stored, so a customer who pasted half
    a token is told immediately rather than after provisioning fails. After this the
    token is never shown again — not in the API, not in the admin.
    """
    if instance.status != BotPlatformInstance.Status.AWAITING_TOKEN:
        raise ConflictError(
            code="bots.not_awaiting_token",
            message="This bot is not waiting for a token.",
        )

    from apps.provisioning.provisioners import get_provisioner

    provisioner = get_provisioner(instance.platform)
    if provisioner is None:
        raise ConflictError(
            code="bots.platform_unavailable",
            message="This platform is not available yet.",
        )

    token = credential_service.validate_token_shape(token)

    try:
        identity = provisioner.verify(token)
    except PlatformApiError as exc:
        raise ConflictError(code="bots.token_rejected", message=str(exc)) from None

    credential_service.store_token(instance=instance, token=token, actor=user)

    instance.platform_bot_id = identity.platform_bot_id
    instance.username = identity.username
    instance.display_name = identity.display_name
    instance.status = BotPlatformInstance.Status.CONFIGURING
    instance.save(
        update_fields=[
            "platform_bot_id",
            "username",
            "display_name",
            "status",
            "updated_at",
        ]
    )

    record_audit(
        actor=user,
        action="bot.token_submitted",
        resource_type="bot_platform_instance",
        resource_id=str(instance.public_id),
        tenant=instance.bot.tenant,
        metadata={"platform": instance.platform, "username": identity.username},
    )

    # Resume the saga now that the thing it was waiting for exists.
    transaction.on_commit(lambda: _resume_provisioning(instance))
    return instance


def _resume_provisioning(instance: BotPlatformInstance) -> None:
    import logging

    from apps.provisioning.tasks import resume_job

    logger = logging.getLogger(__name__)
    job = instance.bot.jobs.order_by("-created_at").first()
    if job is None:
        return
    try:
        resume_job.delay(str(job.public_id))
    except Exception:
        # The token is stored; an operator can retry from the admin. Never fail the
        # customer's submission over a broker hiccup.
        logger.warning("Could not resume provisioning job %s", job.public_id, exc_info=True)


@transaction.atomic
def update_configuration(*, bot: Bot, actor, **fields) -> Bot:
    """Apply the settings a customer is allowed to change (spec §24)."""
    changed: list[str] = []

    for key in ("name", "default_locale", "timezone"):
        if fields.get(key):
            setattr(bot, key, fields[key])
            changed.append(key)
    if changed:
        bot.save(update_fields=[*changed, "updated_at"])

    if "welcome_message" in fields:
        configuration = bot.configuration
        configuration.welcome_message = fields["welcome_message"]
        configuration.save(update_fields=["welcome_message", "updated_at"])
        # Bumping the version invalidates the runtime cache, so the change is live on
        # the next message rather than after a TTL.
        configuration.bump()
        changed.append("welcome_message")

    record_audit(
        actor=actor,
        action="bot.configuration_updated",
        resource_type="bot",
        resource_id=str(bot.public_id),
        tenant=bot.tenant,
        metadata={"fields": changed},
    )
    return bot


def available_addon_features(bot: Bot) -> list[dict]:
    """Catalogue features this bot could add, each with its price (spec §24 upsell).

    "Available" means: offered by the bot's template, not already enabled, and
    deliverable on every platform the bot actually runs on — the same three gates the
    builder applies, just evaluated against a live bot instead of a fresh quote.
    """
    from apps.features.models import Feature
    from apps.features.services import unavailable_selections
    from apps.pricing.services import live_prices, resolve_price_list

    owned = set(bot.bot_features.filter(is_enabled=True).values_list("feature__slug", flat=True))
    offered = (
        bot.template.template_features.filter(feature__is_active=True)
        .exclude(feature__slug__in=owned)
        .select_related("feature")
    )
    platforms = list(bot.instances.values_list("platform", flat=True))
    if not platforms:
        return []

    candidate_slugs = [row.feature.slug for row in offered]
    blocked = {p.feature_slug for p in unavailable_selections(candidate_slugs, platforms)}

    try:
        price_list = resolve_price_list(currency=bot.currency, country=bot.tenant.country)
        prices = live_prices(price_list)
    except NotFoundError:
        # No price list for this bot's currency. Still list the features — a customer
        # should see what exists even if operations has not priced it in this currency
        # yet — just with zero amounts rather than a failed page.
        prices = {}
        price_list = None

    results = []
    for row in offered:
        feature: Feature = row.feature
        if feature.slug in blocked:
            continue

        setup = prices.get(f"feature.{feature.slug}.setup")
        monthly = prices.get(f"feature.{feature.slug}.monthly")
        results.append(
            {
                "slug": feature.slug,
                "name": feature.name,
                "description": feature.description,
                "icon": feature.icon,
                "currency": price_list.currency if price_list else bot.currency,
                "setup_amount_minor": setup.amount_minor if setup else 0,
                "monthly_amount_minor": monthly.amount_minor if monthly else 0,
            }
        )
    return results


def get_bot_for_tenant(*, public_id: str, tenant) -> Bot:
    bot = (
        Bot.objects.filter(public_id=public_id, tenant=tenant)
        .select_related("template", "configuration")
        .prefetch_related("instances", "bot_features__feature")
        .first()
    )
    if bot is None:
        raise NotFoundError()
    return bot


def touch_activity(bot_id: int) -> None:
    Bot.objects.filter(pk=bot_id).update(last_activity_at=timezone.now())
