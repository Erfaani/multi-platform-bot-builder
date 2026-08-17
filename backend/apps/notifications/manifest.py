from __future__ import annotations

from apps.features.manifests import FeatureCategory, FeatureManifest, PreviewStep
from apps.platforms.base import Reply

OWNER_NOTIFICATIONS = FeatureManifest(
    slug="owner_notifications",
    category=FeatureCategory.NOTIFICATIONS,
    name_key="feature.owner_notifications.name",
    description_key="feature.owner_notifications.description",
    icon="bell",
    requires=("business_profile",),
    price_keys=("feature.owner_notifications.setup", "feature.owner_notifications.monthly"),
    preview=(
        PreviewStep(
            title_key="preview.step.owner_notification",
            reply=Reply(text_key="bot.notifications.new_activity"),
        ),
    ),
)

CUSTOMER_BROADCAST = FeatureManifest(
    slug="customer_broadcast",
    category=FeatureCategory.NOTIFICATIONS,
    name_key="feature.customer_broadcast.name",
    description_key="feature.customer_broadcast.description",
    icon="megaphone",
    requires=("business_profile",),
    price_keys=("feature.customer_broadcast.setup", "feature.customer_broadcast.monthly"),
)

MANIFESTS = (OWNER_NOTIFICATIONS, CUSTOMER_BROADCAST)
