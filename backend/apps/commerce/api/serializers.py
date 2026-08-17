from __future__ import annotations

from rest_framework import serializers

from apps.commerce.models import BusinessOrder, BusinessOrderItem, Product, ProductCategory, TableReservation
from apps.core.formatting import money_to_representation
from apps.core.money import Money


class ProductCategorySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductCategory
        fields = ("id", "name", "sort_order", "is_active")


class ProductCategoryWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    sort_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)


class ProductSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    category_id = serializers.IntegerField(source="category.id", read_only=True, default=None)
    price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id", "category_id", "name", "description", "price", "stock", "is_active", "sort_order",
        )

    def get_price(self, obj: Product) -> dict:
        return money_to_representation(
            Money(obj.price_minor, obj.currency), locale=self.context.get("locale", "en")
        )


class ProductWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    price_minor = serializers.IntegerField(required=False, min_value=0)
    currency = serializers.CharField(max_length=8, required=False, allow_blank=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    stock = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class BusinessOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessOrderItem
        fields = ("product_name", "unit_price_minor", "currency", "quantity")


class BusinessOrderSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    contact_name = serializers.CharField(source="contact.display_name", read_only=True)
    subtotal = serializers.SerializerMethodField()
    items = BusinessOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = BusinessOrder
        fields = ("id", "status", "subtotal", "contact_name", "delivery_address", "notes", "items", "created_at")

    def get_subtotal(self, obj: BusinessOrder) -> dict:
        return money_to_representation(
            Money(obj.subtotal_minor, obj.currency), locale=self.context.get("locale", "en")
        )


class TableReservationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    contact_name = serializers.CharField(source="contact.display_name", read_only=True)

    class Meta:
        model = TableReservation
        fields = ("id", "party_size", "starts_at", "status", "notes", "contact_name", "created_at")
