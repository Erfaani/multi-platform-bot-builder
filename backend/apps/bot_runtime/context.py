"""BotContext resolution (BOT_RUNTIME.md §3).

Every inbound update must resolve to *who this bot belongs to* before anything else
happens. That lookup is on the hot path for every message on the platform, so it is
cached — keyed on the configuration version, which means a settings change invalidates
the entry with no broadcast and no stale window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.cache import cache

from apps.bots.models import BotPlatformInstance

CACHE_TTL = 600
CACHE_PREFIX = "botctx"


@dataclass(frozen=True, slots=True)
class BotContext:
    """Everything a handler needs, and nothing that would let it reach another tenant."""

    instance_id: int
    instance_public_id: str
    bot_id: int
    bot_public_id: str
    tenant_id: int
    platform: str
    username: str

    bot_name: str
    default_locale: str
    timezone: str
    currency: str

    template_slug: str
    enabled_features: tuple[str, ...] = ()
    feature_config: dict = field(default_factory=dict)

    welcome_message: str = ""
    branding: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    configuration_version: int = 1

    def has_feature(self, slug: str) -> bool:
        return slug in self.enabled_features

    @property
    def business(self) -> dict:
        return self.branding.get("business", {}) or {}


def _cache_key(instance_public_id: str, version: int) -> str:
    return f"{CACHE_PREFIX}:{instance_public_id}:v{version}"


def _resolve_business(bot, configuration) -> dict:
    """The business dict callers reach through `BotContext.business`.

    `apps.businesses.BusinessProfile` is the live, editable source (spec §24). Bots
    provisioned before it existed — or a bot mid-provisioning, before its profile row is
    created — fall back to the JSON snapshot `BotConfiguration.branding` was seeded with,
    so a handler never sees an unexplained blank.
    """
    from apps.businesses.services import business_context_dict

    live = business_context_dict(bot)
    if live:
        return live
    return (getattr(configuration, "branding", {}) or {}).get("business", {}) or {}


def _build(instance: BotPlatformInstance) -> BotContext:
    bot = instance.bot
    configuration = getattr(bot, "configuration", None)

    enabled = tuple(
        bot.bot_features.filter(is_enabled=True)
        .order_by("feature__sort_order")
        .values_list("feature__slug", flat=True)
    )
    feature_config = {
        row.feature.slug: row.config
        for row in bot.bot_features.select_related("feature").filter(is_enabled=True)
    }

    branding = dict(getattr(configuration, "branding", {}) or {})
    branding["business"] = _resolve_business(bot, configuration)

    return BotContext(
        instance_id=instance.pk,
        instance_public_id=str(instance.public_id),
        bot_id=bot.pk,
        bot_public_id=str(bot.public_id),
        tenant_id=bot.tenant_id,
        platform=instance.platform,
        username=instance.username,
        bot_name=bot.name,
        default_locale=bot.default_locale,
        timezone=bot.timezone,
        currency=bot.currency,
        template_slug=bot.template.slug,
        enabled_features=enabled,
        feature_config=feature_config,
        welcome_message=getattr(configuration, "welcome_message", "") or "",
        branding=branding,
        settings=getattr(configuration, "settings", {}) or {},
        configuration_version=getattr(configuration, "version", 1),
    )


def resolve_context(instance: BotPlatformInstance) -> BotContext:
    """Build or fetch the cached context for an instance."""
    version = getattr(getattr(instance.bot, "configuration", None), "version", 1)
    key = _cache_key(str(instance.public_id), version)

    cached = cache.get(key)
    if cached is not None:
        return cached

    context = _build(instance)
    cache.set(key, context, CACHE_TTL)
    return context


def invalidate_context(instance_public_id: str, version: int) -> None:
    cache.delete(_cache_key(instance_public_id, version))


def load_instance(platform: str, instance_public_id: str) -> BotPlatformInstance | None:
    """Fetch an instance for the ingress path.

    Returns None for anything not currently able to receive traffic — unknown,
    suspended, or a platform mismatch. The caller answers 200 and drops, so the
    platform neither retries nor learns whether the bot exists.
    """
    return (
        BotPlatformInstance.objects.select_related("bot", "bot__tenant", "bot__configuration")
        .filter(
            public_id=instance_public_id,
            platform=platform,
            status=BotPlatformInstance.Status.ACTIVE,
            bot__status="ACTIVE",
        )
        .first()
    )
