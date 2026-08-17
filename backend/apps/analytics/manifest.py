from __future__ import annotations

from apps.features.manifests import FeatureCategory, FeatureManifest

ANALYTICS = FeatureManifest(
    slug="analytics",
    category=FeatureCategory.ANALYTICS,
    name_key="feature.analytics.name",
    description_key="feature.analytics.description",
    icon="bar-chart",
    requires=("business_profile",),
    price_keys=("feature.analytics.setup", "feature.analytics.monthly"),
    permissions=("analytics.view",),
)

MANIFESTS = (ANALYTICS,)
