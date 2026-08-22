"""Core business features.

Phase 2 declares the sellable and previewable half of each feature. Runtime handlers
and models arrive in Phase 7; the manifest shape does not change when they do.
"""

from __future__ import annotations

from apps.features.manifests import (
    CollectItemField,
    CollectSchema,
    FeatureCategory,
    FeatureManifest,
    MenuEntry,
    PreviewStep,
)
from apps.platforms.base import Choice, Reply

BUSINESS_PROFILE = FeatureManifest(
    slug="business_profile",
    category=FeatureCategory.CORE,
    name_key="feature.business_profile.name",
    description_key="feature.business_profile.description",
    icon="building",
    always_on=True,  # a bot with no business identity is not a product
    menu=(
        MenuEntry(label_key="menu.about", route="business:about", sort_order=10),
        # Telegram-only in practice (`core:open_app`'s own handler explains why on any
        # other platform) — kept on every bot rather than gated by feature/platform so
        # the entry point stays a normal, always-declarative MenuEntry; see
        # apps.platforms.base.Choice.web_app_url for how the actual button degrades.
        MenuEntry(label_key="menu.open_app", route="core:open_app", sort_order=15),
    ),
    price_keys=("feature.business_profile.setup",),
    permissions=("business.view", "business.manage"),
    preview=(
        PreviewStep(
            title_key="preview.step.welcome",
            reply=Reply(
                text_key="bot.welcome",
                params={"business": "{business_name}"},
                choices=[
                    Choice(label_key="menu.about", value="business:about"),
                    Choice(label_key="menu.contact", value="business:contact"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.about",
            user_says_key="menu.about",
            reply=Reply(text_key="bot.business.about", params={"business": "{business_name}"}),
        ),
    ),
)

CONTACT = FeatureManifest(
    slug="contact",
    category=FeatureCategory.CORE,
    name_key="feature.contact.name",
    description_key="feature.contact.description",
    icon="phone",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.contact", route="business:contact", sort_order=20),),
    price_keys=("feature.contact.setup",),
    preview=(
        PreviewStep(
            title_key="preview.step.contact",
            user_says_key="menu.contact",
            reply=Reply(text_key="bot.business.contact"),
        ),
    ),
)

LOCATION = FeatureManifest(
    slug="location",
    category=FeatureCategory.CORE,
    name_key="feature.location.name",
    description_key="feature.location.description",
    icon="map-pin",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.location", route="business:location", sort_order=30),),
    price_keys=("feature.location.setup",),
    preview=(
        PreviewStep(
            title_key="preview.step.location",
            user_says_key="menu.location",
            reply=Reply(text_key="bot.business.location"),
        ),
    ),
)

WORKING_HOURS = FeatureManifest(
    slug="working_hours",
    category=FeatureCategory.CORE,
    name_key="feature.working_hours.name",
    description_key="feature.working_hours.description",
    icon="clock",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.working_hours", route="business:hours", sort_order=40),),
    price_keys=("feature.working_hours.setup",),
    preview=(
        PreviewStep(
            title_key="preview.step.hours",
            user_says_key="menu.working_hours",
            reply=Reply(text_key="bot.business.hours"),
        ),
    ),
)

FAQ = FeatureManifest(
    slug="faq",
    category=FeatureCategory.CORE,
    name_key="feature.faq.name",
    description_key="feature.faq.description",
    icon="help-circle",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.faq", route="faq:list", sort_order=50),),
    price_keys=("feature.faq.setup",),
    permissions=("faq.manage",),
    preview=(
        PreviewStep(
            title_key="preview.step.faq",
            user_says_key="menu.faq",
            reply=Reply(
                text_key="bot.faq.prompt",
                choices=[
                    Choice(label_key="bot.faq.sample_question_1", value="faq:1"),
                    Choice(label_key="bot.faq.sample_question_2", value="faq:2"),
                ],
            ),
        ),
    ),
    collects=CollectSchema(
        kind="repeatable_form",
        title_key="builder.collect.faq.title",
        hint_key="builder.collect.faq.hint",
        fields=(
            CollectItemField(key="question", label_key="builder.collect.faq.question", max_length=255),
            CollectItemField(
                key="answer",
                label_key="builder.collect.faq.answer",
                kind="textarea",
                max_length=2000,
            ),
        ),
        add_label_key="builder.collect.faq.add",
        max_items=50,
    ),
)

CUSTOM_MENU = FeatureManifest(
    slug="custom_menu",
    category=FeatureCategory.CORE,
    name_key="feature.custom_menu.name",
    description_key="feature.custom_menu.description",
    icon="list",
    requires=("business_profile",),
    price_keys=("feature.custom_menu.setup",),
)

MANIFESTS = (
    BUSINESS_PROFILE,
    CONTACT,
    LOCATION,
    WORKING_HOURS,
    FAQ,
    CUSTOM_MENU,
)
