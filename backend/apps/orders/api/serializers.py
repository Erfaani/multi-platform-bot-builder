from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.core.formatting import money_to_representation
from apps.i18n_content.services import translate as translate_content
from apps.orders.models import Quote, QuoteItem, QuoteSource
from apps.platforms.constants import SELLABLE_PLATFORMS
from apps.platforms.preview.messages import translate as translate_bot

#: Brand names, kept in their own script per locale rather than left in Latin for a
#: Persian reader — everything else about a line item follows the same rule via
#: `i18n_content.translate`, this is just the one place with no database row to read.
_PLATFORM_NAMES = {
    "telegram": {"en": "Telegram", "fa": "تلگرام"},
    "bale": {"en": "Bale", "fa": "بله"},
}


class BuildQuoteSerializer(serializers.Serializer):
    """The builder's input. Notice there is no price field anywhere — by design."""

    template = serializers.SlugField()
    platforms = serializers.ListField(
        child=serializers.ChoiceField(choices=SELLABLE_PLATFORMS),
        allow_empty=False,
        max_length=len(SELLABLE_PLATFORMS),
    )
    features = serializers.ListField(
        child=serializers.SlugField(), allow_empty=True, required=False, default=list
    )
    currency = serializers.ChoiceField(
        choices=settings.ACTIVE_CURRENCIES, required=False, allow_null=True
    )
    country = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    business = serializers.DictField(required=False, default=dict)
    created_via = serializers.ChoiceField(
        choices=QuoteSource.choices, required=False, default=QuoteSource.WEB
    )

    def validate(self, attrs: dict) -> dict:
        """Clean `business["feature_config"]` against each feature's own `CollectSchema`
        (dynamic configuration, Phase 10.5) — the one part of `business` that isn't free
        text a customer types about their own business, so it's the one part worth
        validating here rather than trusting silently, the same way the rest of this
        serializer never accepts a price from the client."""
        from apps.features.manifests import validate_collected_items
        from apps.features.registry import all_manifests

        business = attrs.get("business") or {}
        feature_config = business.get("feature_config")
        if isinstance(feature_config, dict):
            manifests = all_manifests()
            selected = set(attrs.get("features") or ())
            cleaned_config = {}
            for slug, raw_items in feature_config.items():
                # Content for a feature the customer did not actually select is dropped,
                # not just unused — `resolved_features` (auto-added dependencies) can
                # differ from this list, but collecting content for something never
                # chosen at all is either a stale client state or tampering, not a
                # legitimate case to seed content for.
                if slug not in selected:
                    continue
                manifest = manifests.get(slug)
                if manifest is None or manifest.collects is None:
                    continue
                cleaned = validate_collected_items(manifest.collects, raw_items)
                if cleaned:
                    cleaned_config[slug] = cleaned
            attrs["business"] = {**business, "feature_config": cleaned_config}
        return attrs


class QuoteItemSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    unit_amount = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()

    class Meta:
        model = QuoteItem
        fields = (
            "price_key",
            "label",
            "feature_slug",
            "quantity",
            "billing_kind",
            "unit_amount",
            "amount",
        )

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_label(self, obj: QuoteItem) -> str:
        return _price_label(obj, self._locale())

    def get_unit_amount(self, obj: QuoteItem) -> dict | None:
        return money_to_representation(obj.unit_amount, locale=self._locale())

    def get_amount(self, obj: QuoteItem) -> dict | None:
        return money_to_representation(obj.amount, locale=self._locale())


def _price_label(item: QuoteItem, locale: str) -> str:
    """Human label for a line.

    Falls back to the feature's own name so a new price key never renders as a raw
    identifier in front of a paying customer.
    """
    from apps.features.models import Feature

    if item.feature_slug:
        feature = Feature.objects.filter(slug=item.feature_slug).first()
        if feature is not None:
            name = translate_content(feature, "name", locale=locale, source=feature.name)
            suffix = item.price_key.rsplit(".", 1)[-1]
            if suffix == "monthly":
                monthly_suffix = {"en": " (monthly)", "fa": " (ماهانه)"}
                return f"{name}{monthly_suffix.get(locale, monthly_suffix['en'])}"
            return name

    known = {
        "platform.multi.surcharge": {
            "en": "Multi-platform setup",
            "fa": "راه‌اندازی چندپلتفرمی",
        },
        "hosting.standard.monthly": {"en": "Hosting (monthly)", "fa": "میزبانی (ماهانه)"},
    }
    if item.price_key in known:
        entry = known[item.price_key]
        return entry.get(locale, entry["en"])

    if item.price_key.startswith("platform."):
        slug = item.price_key.split(".")[1]
        names = _PLATFORM_NAMES.get(slug)
        if names:
            return names.get(locale, names["en"])
        return slug.title()

    if item.price_key.startswith("template."):
        from apps.business_templates.models import BusinessTemplate

        slug = item.price_key.split(".")[1]
        template = BusinessTemplate.objects.filter(slug=slug).first()
        if template is not None:
            name = translate_content(template, "name", locale=locale, source=template.name)
            if locale == "fa":
                return f"راه‌اندازی {name}"
            return f"{name} setup"

    return translate_bot(item.label_key, locale=locale)


class QuoteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    template = serializers.CharField(source="template.slug", read_only=True)
    items = serializers.SerializerMethodField()
    subtotal_once = serializers.SerializerMethodField()
    subtotal_recurring = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    is_claimed = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quote
        fields = (
            "id",
            "template",
            "platforms",
            "selected_features",
            "resolved_features",
            "business_draft",
            "locale",
            "currency",
            "items",
            "subtotal_once",
            "subtotal_recurring",
            "total",
            "is_claimed",
            "is_expired",
            "expires_at",
            "created_at",
        )

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_items(self, obj: Quote) -> list[dict]:
        return QuoteItemSerializer(
            obj.items.all(), many=True, context={"locale": self._locale()}
        ).data

    def get_subtotal_once(self, obj: Quote) -> dict | None:
        return money_to_representation(obj.subtotal_once, locale=self._locale())

    def get_subtotal_recurring(self, obj: Quote) -> dict | None:
        return money_to_representation(obj.subtotal_recurring, locale=self._locale())

    def get_total(self, obj: Quote) -> dict | None:
        return money_to_representation(obj.total, locale=self._locale())


class PreviewRequestSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=128, required=False, default="")
