from __future__ import annotations

from apps.features.manifests import FeatureCategory, FeatureManifest, MenuEntry, PreviewStep
from apps.platforms.base import Reply

CONTACT_REQUEST = FeatureManifest(
    slug="contact_request",
    category=FeatureCategory.INTERACTION,
    name_key="feature.contact_request.name",
    description_key="feature.contact_request.description",
    icon="message-square",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.contact_us", route="crm:contact", sort_order=60),),
    price_keys=("feature.contact_request.setup",),
    preview=(
        PreviewStep(
            title_key="preview.step.contact_request",
            user_says_key="menu.contact_us",
            reply=Reply(text_key="bot.crm.ask_message", expects="text"),
        ),
    ),
)

CONSULTATION_REQUEST = FeatureManifest(
    slug="consultation_request",
    category=FeatureCategory.INTERACTION,
    name_key="feature.consultation_request.name",
    description_key="feature.consultation_request.description",
    icon="handshake",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.consultation", route="crm:consultation", sort_order=61),),
    price_keys=("feature.consultation_request.setup",),
    preview=(
        PreviewStep(
            title_key="preview.step.consultation",
            user_says_key="menu.consultation",
            reply=Reply(text_key="bot.crm.ask_phone", expects="phone"),
        ),
    ),
)

LEAD_CAPTURE = FeatureManifest(
    slug="lead_capture",
    category=FeatureCategory.CRM,
    name_key="feature.lead_capture.name",
    description_key="feature.lead_capture.description",
    icon="user-plus",
    requires=("business_profile",),
    price_keys=("feature.lead_capture.setup", "feature.lead_capture.monthly"),
    permissions=("crm.view", "crm.manage"),
)

CRM_PIPELINE = FeatureManifest(
    slug="crm_pipeline",
    category=FeatureCategory.CRM,
    name_key="feature.crm_pipeline.name",
    description_key="feature.crm_pipeline.description",
    icon="kanban",
    requires=("lead_capture",),
    price_keys=("feature.crm_pipeline.setup", "feature.crm_pipeline.monthly"),
    permissions=("crm.view", "crm.manage"),
)

FEEDBACK = FeatureManifest(
    slug="feedback",
    category=FeatureCategory.INTERACTION,
    name_key="feature.feedback.name",
    description_key="feature.feedback.description",
    icon="star",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.feedback", route="crm:feedback", sort_order=70),),
    price_keys=("feature.feedback.setup",),
    preview=(
        PreviewStep(
            title_key="preview.step.feedback",
            user_says_key="menu.feedback",
            reply=Reply(text_key="bot.crm.ask_rating"),
        ),
    ),
)

MANIFESTS = (
    CONTACT_REQUEST,
    CONSULTATION_REQUEST,
    LEAD_CAPTURE,
    CRM_PIPELINE,
    FEEDBACK,
)
