from __future__ import annotations

from apps.features.manifests import (
    CollectItemField,
    CollectOption,
    CollectSchema,
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

PROPERTY_LISTINGS = FeatureManifest(
    slug="property_listings",
    category=FeatureCategory.COMMERCE,
    name_key="feature.property_listings.name",
    description_key="feature.property_listings.description",
    icon="home",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.properties", route="property_listings:list", sort_order=5),),
    price_keys=("feature.property_listings.setup", "feature.property_listings.monthly"),
    permissions=("commerce.view", "commerce.manage"),
    preview=(
        PreviewStep(
            title_key="preview.step.properties",
            user_says_key="menu.properties",
            reply=Reply(
                text_key="bot.commerce.select_property",
                choices=[
                    Choice(label_key="bot.commerce.sample_property_1", value="property_listings:detail.1"),
                    Choice(label_key="bot.commerce.sample_property_2", value="property_listings:detail.2"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.property_detail",
            reply=Reply(text_key="bot.commerce.property_detail"),
        ),
    ),
    collects=CollectSchema(
        kind="repeatable_form",
        title_key="builder.collect.property_listings.title",
        hint_key="builder.collect.property_listings.hint",
        fields=(
            CollectItemField(key="title", label_key="builder.collect.property_listings.title_field", max_length=128),
            CollectItemField(
                key="listing_type",
                label_key="builder.collect.property_listings.listing_type",
                kind="select",
                options=(
                    CollectOption(value="SALE", label_key="builder.collect.property_listings.sale"),
                    CollectOption(value="RENT", label_key="builder.collect.property_listings.rent"),
                ),
            ),
            CollectItemField(
                key="property_type",
                label_key="builder.collect.property_listings.property_type",
                kind="select",
                options=(
                    CollectOption(value="APARTMENT", label_key="builder.collect.property_listings.apartment"),
                    CollectOption(value="HOUSE", label_key="builder.collect.property_listings.house"),
                    CollectOption(value="LAND", label_key="builder.collect.property_listings.land"),
                    CollectOption(value="COMMERCIAL", label_key="builder.collect.property_listings.commercial"),
                ),
            ),
            CollectItemField(key="price", label_key="builder.collect.property_listings.price", max_length=32),
            CollectItemField(
                key="address", label_key="builder.collect.property_listings.address",
                required=False, max_length=255,
            ),
            CollectItemField(
                key="description", label_key="builder.collect.property_listings.description",
                kind="textarea", required=False, max_length=2000,
            ),
        ),
        add_label_key="builder.collect.property_listings.add",
        max_items=30,
    ),
)

COURSE_CATALOG = FeatureManifest(
    slug="course_catalog",
    category=FeatureCategory.COMMERCE,
    name_key="feature.course_catalog.name",
    description_key="feature.course_catalog.description",
    icon="graduation-cap",
    requires=("business_profile",),
    menu=(MenuEntry(label_key="menu.courses", route="course_catalog:list", sort_order=5),),
    price_keys=("feature.course_catalog.setup", "feature.course_catalog.monthly"),
    permissions=("commerce.view", "commerce.manage"),
    preview=(
        PreviewStep(
            title_key="preview.step.courses",
            user_says_key="menu.courses",
            reply=Reply(
                text_key="bot.commerce.select_course",
                choices=[
                    Choice(label_key="bot.commerce.sample_course_1", value="course_catalog:detail.1"),
                    Choice(label_key="bot.commerce.sample_course_2", value="course_catalog:detail.2"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.course_detail",
            reply=Reply(text_key="bot.commerce.course_detail"),
        ),
    ),
    collects=CollectSchema(
        kind="repeatable_form",
        title_key="builder.collect.course_catalog.title",
        hint_key="builder.collect.course_catalog.hint",
        fields=(
            CollectItemField(key="title", label_key="builder.collect.course_catalog.title_field", max_length=128),
            CollectItemField(
                key="instructor_name", label_key="builder.collect.course_catalog.instructor",
                required=False, max_length=128,
            ),
            CollectItemField(key="price", label_key="builder.collect.course_catalog.price", max_length=32),
            CollectItemField(
                key="duration_label", label_key="builder.collect.course_catalog.duration",
                required=False, max_length=64,
            ),
            CollectItemField(
                key="description", label_key="builder.collect.course_catalog.description",
                kind="textarea", required=False, max_length=2000,
            ),
        ),
        add_label_key="builder.collect.course_catalog.add",
        max_items=30,
    ),
)

MANIFESTS = (
    PRODUCT_CATALOG,
    CART_ORDERS,
    TABLE_RESERVATION,
    FOOD_ORDERING,
    PROPERTY_LISTINGS,
    COURSE_CATALOG,
)
