from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.core.formatting import money_to_representation
from apps.orders.models import Quote, QuoteItem, QuoteSource
from apps.platforms.constants import SELLABLE_PLATFORMS
from apps.platforms.preview.messages import translate as translate_bot


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
            suffix = item.price_key.rsplit(".", 1)[-1]
            if suffix == "monthly":
                return f"{feature.name} (monthly)"
            return feature.name

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
        return slug.title()

    if item.price_key.startswith("template."):
        from apps.business_templates.models import BusinessTemplate

        slug = item.price_key.split(".")[1]
        template = BusinessTemplate.objects.filter(slug=slug).first()
        if template is not None:
            return f"{template.name} setup"

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
