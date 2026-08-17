from rest_framework import serializers

from apps.core.models import Currency


class CurrencySerializer(serializers.ModelSerializer):
    """Formatting metadata the frontend needs to render amounts itself."""

    class Meta:
        model = Currency
        fields = (
            "code",
            "name",
            "symbol",
            "exponent",
            "display_unit",
            "display_divisor",
        )


class MoneySerializer(serializers.Serializer):
    """Read-only representation of an amount (API.md §1)."""

    amount_minor = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    formatted = serializers.CharField(read_only=True)


class PublicSettingsSerializer(serializers.Serializer):
    brand_name = serializers.CharField()
    default_locale = serializers.CharField()
    active_locales = serializers.ListField(child=serializers.CharField())
    rtl_locales = serializers.ListField(child=serializers.CharField())
    default_currency = serializers.CharField()
    maintenance_mode = serializers.BooleanField()
    settings = serializers.DictField()
