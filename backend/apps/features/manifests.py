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
    "CollectOption",
    "CollectItemField",
    "CollectSchema",
    "FeatureManifest",
    "validate_collected_items",
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
class CollectOption:
    """One choice within a `kind="select"` field (e.g. property listing type)."""

    value: str
    label_key: str


@dataclass(frozen=True, slots=True)
class CollectItemField:
    """One input within a single collected item (e.g. FAQ's "question" and "answer",
    or a property's "listing type")."""

    key: str
    label_key: str
    kind: str = "text"  # "text" | "textarea" | "select"
    required: bool = True
    max_length: int = 255
    #: Only meaningful when `kind == "select"`.
    options: tuple[CollectOption, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectSchema:
    """Declares that a feature needs specific content from the customer, and what shape
    it takes — read by the builder to ask a feature-specific question instead of a
    generic one (e.g. FAQ: "enter your questions and answers", not "tell us about your
    business" again).

    `kind="repeatable_form"` is the only shape — an add/edit/delete list of items, each
    with the fields below. It covers both "many small pieces of content" (FAQ's Q&A
    pairs) and "how would you like to add your X" (real estate's properties, academy's
    courses): filling the list in *is* "add manually," and the builder's own optional-
    skip affordance (leaving it empty) already covers "manage this later from the bot
    management panel" — no separate choice-first UI needed for that distinction.
    """

    kind: str
    title_key: str
    hint_key: str = ""
    fields: tuple[CollectItemField, ...] = ()
    add_label_key: str = ""
    max_items: int = 50


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

    #: What this feature needs from the customer beyond the generic business details —
    #: `None` (the common case) means no extra builder step.
    collects: CollectSchema | None = None

    def default_price_keys(self) -> tuple[str, ...]:
        return self.price_keys or (f"feature.{self.slug}.setup",)


def validate_collected_items(schema: CollectSchema, raw: object) -> list[dict[str, str]]:
    """Clean and validate a `feature_config[<slug>]` list against its feature's own
    `CollectSchema` — shared by the quote-build serializer (so a customer sees a
    validation error immediately) and the provisioning saga (which must never trust that
    data survived untouched between an anonymous quote and the order it became).

    Silently drops items missing a required field or past `max_items`, rather than
    raising, so a customer's 51st FAQ entry is quietly not saved instead of blocking
    everything else they configured — the builder UI is expected to enforce `max_items`
    itself and this is a backstop, not the primary UX.
    """
    if schema.kind != "repeatable_form" or not isinstance(raw, list):
        return []

    cleaned: list[dict[str, str]] = []
    for entry in raw[: schema.max_items]:
        if not isinstance(entry, dict):
            continue
        item: dict[str, str] = {}
        valid = True
        for spec in schema.fields:
            value = str(entry.get(spec.key, "") or "").strip()[: spec.max_length]
            if spec.kind == "select" and value and value not in {opt.value for opt in spec.options}:
                valid = False
                break
            if spec.required and not value:
                valid = False
                break
            item[spec.key] = value
        if valid:
            cleaned.append(item)
    return cleaned
