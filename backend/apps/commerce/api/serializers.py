from __future__ import annotations

from rest_framework import serializers

from apps.commerce.models import (
    BusinessOrder,
    BusinessOrderItem,
    CourseOffering,
    Product,
    ProductCategory,
    ProductImage,
    PropertyImage,
    PropertyListing,
    PropertyListingType,
    PropertyType,
    TableReservation,
)
from apps.core.files import public_file_url
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


class ProductImageSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ("id", "url", "sort_order")

    def get_url(self, obj: ProductImage) -> str:
        return public_file_url(obj.file)


class ProductSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    category_id = serializers.IntegerField(source="category.id", read_only=True, default=None)
    price = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "category_id", "name", "description", "price", "stock", "is_active",
            "sort_order", "images",
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


class PropertyImageSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = PropertyImage
        fields = ("id", "url", "sort_order")

    def get_url(self, obj: PropertyImage) -> str:
        return public_file_url(obj.file)


class PropertyListingSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    price = serializers.SerializerMethodField()
    images = PropertyImageSerializer(many=True, read_only=True)

    class Meta:
        model = PropertyListing
        fields = (
            "id", "title", "description", "listing_type", "property_type", "bedrooms",
            "bathrooms", "area_sqm", "address", "price", "is_active", "sort_order", "images",
        )

    def get_price(self, obj: PropertyListing) -> dict:
        return money_to_representation(
            Money(obj.price_minor, obj.currency), locale=self.context.get("locale", "en")
        )


class PropertyListingWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=128, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    listing_type = serializers.ChoiceField(choices=PropertyListingType.choices, required=False)
    property_type = serializers.ChoiceField(choices=PropertyType.choices, required=False)
    bedrooms = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    bathrooms = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    area_sqm = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    address = serializers.CharField(required=False, allow_blank=True)
    price_minor = serializers.IntegerField(required=False, min_value=0)
    currency = serializers.CharField(max_length=8, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class CourseOfferingSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    price = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = CourseOffering
        fields = (
            "id", "title", "description", "instructor_name", "price", "starts_at",
            "duration_label", "capacity", "enrolled_count", "is_active", "sort_order",
            "thumbnail_url",
        )

    def get_price(self, obj: CourseOffering) -> dict:
        return money_to_representation(
            Money(obj.price_minor, obj.currency), locale=self.context.get("locale", "en")
        )

    def get_thumbnail_url(self, obj: CourseOffering) -> str:
        return public_file_url(obj.thumbnail)


class CourseOfferingWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=128, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    instructor_name = serializers.CharField(max_length=128, required=False, allow_blank=True)
    price_minor = serializers.IntegerField(required=False, min_value=0)
    currency = serializers.CharField(max_length=8, required=False, allow_blank=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    duration_label = serializers.CharField(max_length=64, required=False, allow_blank=True)
    capacity = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    enrolled_count = serializers.IntegerField(required=False, min_value=0)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class ImageUploadSerializer(serializers.Serializer):
    file = serializers.ImageField()
