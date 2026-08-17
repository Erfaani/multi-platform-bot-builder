from __future__ import annotations

from apps.features.manifests import (
    FeatureCategory,
    FeatureManifest,
    MenuEntry,
    PlatformRequirements,
    PreviewStep,
)
from apps.platforms.base import Reply

AI_ASSISTANT = FeatureManifest(
    slug="ai_assistant",
    category=FeatureCategory.AI,
    name_key="feature.ai_assistant.name",
    description_key="feature.ai_assistant.description",
    icon="sparkles",
    # The assistant answers *from the business's own knowledge*, so FAQ is not a
    # nicety — without it there is nothing grounded to answer from and the model
    # will invent opening hours (spec §32).
    requires=("business_profile", "faq"),
    menu=(MenuEntry(label_key="menu.ask", route="ai:ask", sort_order=8),),
    price_keys=("feature.ai_assistant.setup", "feature.ai_assistant.monthly"),
    permissions=("ai.manage",),
    preview=(
        PreviewStep(
            title_key="preview.step.ai_ask",
            user_says_key="menu.ask",
            reply=Reply(text_key="bot.ai.prompt", expects="text"),
        ),
        PreviewStep(
            title_key="preview.step.ai_answer",
            reply=Reply(text_key="bot.ai.sample_answer"),
        ),
    ),
)

AI_KNOWLEDGE_BASE = FeatureManifest(
    slug="ai_knowledge_base",
    category=FeatureCategory.AI,
    name_key="feature.ai_knowledge_base.name",
    description_key="feature.ai_knowledge_base.description",
    icon="book-open",
    requires=("ai_assistant",),
    # Customers upload documents to build the knowledge base.
    platform_requirements=PlatformRequirements(needs_file_uploads=True),
    price_keys=("feature.ai_knowledge_base.setup", "feature.ai_knowledge_base.monthly"),
    permissions=("ai.manage",),
)

MANIFESTS = (AI_ASSISTANT, AI_KNOWLEDGE_BASE)
