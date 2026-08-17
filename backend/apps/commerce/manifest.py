from __future__ import annotations

from apps.features.manifests import (
    FeatureCategory,
    FeatureManifest,
    MenuEntry,
    PlatformRequirements,
    PreviewStep,
)
from apps.platforms.base import Choice, Reply

PRODUCT_CATALOG = FeatureManifest(
    slug="product_catalog",
    category=FeatureCategory.COMMERCE,
    name_key="feature.product_catalog.name",
    description_key="feature.product_catalog.description",
    icon="package",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.catalog", route="commerce:catalog", sort_order=5),),
    price_keys=("feature.product_catalog.setup", "feature.product_catalog.monthly"),
    permissions=("commerce.view", "commerce.manage"),
    preview=(
        PreviewStep(
            title_key="preview.step.catalog",
            user_says_key="menu.catalog",
            reply=Reply(
                text_key="bot.commerce.select_category",
                choices=[
                    Choice(label_key="bot.commerce.sample_category_1", value="cat:1"),
                    Choice(label_key="bot.commerce.sample_category_2", value="cat:2"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.product",
            reply=Reply(
                text_key="bot.commerce.product_detail",
                choices=[Choice(label_key="bot.commerce.add_to_cart", value="cart:add")],
            ),
        ),
    ),
)

CART_ORDERS = FeatureManifest(
    slug="cart_orders",
    category=FeatureCategory.COMMERCE,
    name_key="feature.cart_orders.name",
    description_key="feature.cart_orders.description",
    icon="shopping-cart",
    requires=("product_catalog",),
    menu=(MenuEntry(label_key="menu.cart", route="commerce:cart", sort_order=6),),
    price_keys=("feature.cart_orders.setup", "feature.cart_orders.monthly"),
    preview=(
        PreviewStep(
            title_key="preview.step.cart",
            user_says_key="menu.cart",
            reply=Reply(
                text_key="bot.commerce.cart_summary",
                choices=[Choice(label_key="bot.commerce.checkout", value="cart:checkout")],
            ),
        ),
        PreviewStep(
            title_key="preview.step.order_placed",
            reply=Reply(text_key="bot.commerce.order_placed"),
        ),
    ),
)

TABLE_RESERVATION = FeatureManifest(
    slug="table_reservation",
    category=FeatureCategory.RESTAURANT,
    name_key="feature.table_reservation.name",
    description_key="feature.table_reservation.description",
    icon="utensils",
    requires=("business_profile", "working_hours"),
    menu=(MenuEntry(label_key="menu.reserve", route="restaurant:reserve", sort_order=7),),
    price_keys=("feature.table_reservation.setup", "feature.table_reservation.monthly"),
    preview=(
        PreviewStep(
            title_key="preview.step.reserve",
            user_says_key="menu.reserve",
            reply=Reply(
                text_key="bot.restaurant.select_time",
                choices=[
                    Choice(label_key="bot.restaurant.sample_slot_1", value="t:1"),
                    Choice(label_key="bot.restaurant.sample_slot_2", value="t:2"),
                ],
            ),
        ),
    ),
)

FOOD_ORDERING = FeatureManifest(
    slug="food_ordering",
    category=FeatureCategory.RESTAURANT,
    name_key="feature.food_ordering.name",
    description_key="feature.food_ordering.description",
    icon="chef-hat",
    requires=("product_catalog", "cart_orders"),
    price_keys=("feature.food_ordering.setup", "feature.food_ordering.monthly"),
    # Ordering food without pictures of it is a materially worse product, so this
    # feature genuinely needs media groups rather than merely preferring them.
    platform_requirements=PlatformRequirements(needs_media_groups=True),
    preview=(
        PreviewStep(
            title_key="preview.step.food_order",
            reply=Reply(text_key="bot.restaurant.order_summary"),
        ),
    ),
)

MANIFESTS = (PRODUCT_CATALOG, CART_ORDERS, TABLE_RESERVATION, FOOD_ORDERING)
