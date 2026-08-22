"""The `bot_builder` feature: never sold, never attached to any `BusinessTemplate` —
enabled only on the platform's own permanent "builder" bot (see
`apps.core.management.commands.provision_builder_bot`). Its one menu entry is what lets
a customer order a brand-new bot entirely by chatting, mirroring the website builder
(Phase 10.5 hybrid model's chat-native counterpart).
"""

from __future__ import annotations

from apps.features.manifests import FeatureCategory, FeatureManifest, MenuEntry

BOT_BUILDER = FeatureManifest(
    slug="bot_builder",
    category=FeatureCategory.CORE,
    name_key="feature.bot_builder.name",
    description_key="feature.bot_builder.description",
    icon="hammer",
    menu=(
        MenuEntry(label_key="menu.build_bot", route="builder:start", sort_order=5),
        MenuEntry(label_key="menu.order_status", route="builder:status", sort_order=6),
    ),
)

MANIFESTS = (BOT_BUILDER,)
