"""The feature manifest contract (ARCHITECTURE.md §5).

One declarative object per feature, read by the builder UI, the pricing engine,
provisioning and the runtime. Adding a feature means adding a package; no engine changes.

Manifests live in the app that implements the feature — `apps/appointments/manifest.py`,
`apps/commerce/manifest.py` — and are discovered by `features.registry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from apps.platforms.base import Reply

__all__ = [
    "FeatureCategory",
    "PlatformRequirements",
    "MenuEntry",
    "PreviewStep",
    "FeatureManifest",
]


class FeatureCategory:
    CORE = "core"
    INTERACTION = "interaction"
    APPOINTMENT = "appointment"
    COMMERCE = "commerce"
    RESTAURANT = "restaurant"
    CRM = "crm"
    NOTIFICATIONS = "notifications"
    AI = "ai"
    ANALYTICS = "analytics"

    ALL = (
        CORE,
        INTERACTION,
        APPOINTMENT,
        COMMERCE,
        RESTAURANT,
        CRM,
        NOTIFICATIONS,
        AI,
        ANALYTICS,
    )


@dataclass(frozen=True, slots=True)
class PlatformRequirements:
    """Capabilities a feature genuinely needs to function.

    Checked against each adapter's `Capabilities`, so a feature that cannot work on a
    channel is never offered for sale there (docs/00-ANALYSIS.md R-02). Requiring
    nothing is the common case — most features degrade fine.
    """

    needs_inline_keyboards: bool = False
    needs_file_uploads: bool = False
    needs_web_app: bool = False
    needs_media_groups: bool = False

    def unmet_on(self, capabilities) -> list[str]:
        missing = []
        if self.needs_inline_keyboards and not capabilities.inline_keyboards:
            missing.append("inline_keyboards")
        if self.needs_file_uploads and not capabilities.file_uploads:
            missing.append("file_uploads")
        if self.needs_web_app and not capabilities.web_app:
            missing.append("web_app")
        if self.needs_media_groups and not capabilities.media_groups:
            missing.append("media_groups")
        return missing


@dataclass(frozen=True, slots=True)
class MenuEntry:
    """An entry this feature contributes to the bot's main menu."""

    label_key: str
    route: str
    sort_order: int = 100


@dataclass(frozen=True, slots=True)
class PreviewStep:
    """A sample interaction shown in the pre-payment preview (spec §48).

    Written by the feature author because they know what the flow looks like; the
    preview engine just plays them back through an adapter.
    """

    title_key: str
    reply: Reply
    user_says_key: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureManifest:
    slug: str
    category: str
    name_key: str
    description_key: str
    icon: str = "sparkles"

    #: Slugs that must also be enabled. Enforced when a quote is built, so an
    #: impossible combination cannot be sold.
    requires: tuple[str, ...] = ()

    platform_requirements: PlatformRequirements = field(default_factory=PlatformRequirements)
    menu: tuple[MenuEntry, ...] = ()
    preview: tuple[PreviewStep, ...] = ()

    #: Price keys this feature contributes. Prices themselves live in the database.
    price_keys: tuple[str, ...] = ()

    #: Tenant scopes the feature introduces (used by the dashboard in Phase 6).
    permissions: tuple[str, ...] = ()

    #: Runtime handlers, filled in by the implementing app in Phase 7.
    handlers: dict[str, Callable[..., Any]] = field(default_factory=dict)

    #: True when the feature is part of every bot and cannot be deselected.
    always_on: bool = False

    def default_price_keys(self) -> tuple[str, ...]:
        return self.price_keys or (f"feature.{self.slug}.setup",)
