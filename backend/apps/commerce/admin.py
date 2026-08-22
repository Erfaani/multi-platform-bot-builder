from django.contrib import admin

from apps.commerce.models import (
    BusinessOrder,
    BusinessOrderItem,
    Cart,
    CartItem,
    CourseOffering,
    Product,
    ProductCategory,
    ProductImage,
    PropertyImage,
    PropertyListing,
    TableReservation,
)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "bot", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "bot", "category", "price", "stock", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot", "category")
    inlines = (ProductImageInline,)


class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 0


@admin.register(PropertyListing)
class PropertyListingAdmin(admin.ModelAdmin):
    list_display = ("title", "bot", "listing_type", "property_type", "price", "is_active")
    list_filter = ("is_active", "listing_type", "property_type")
    search_fields = ("title", "bot__name", "address")
    autocomplete_fields = ("tenant", "bot")
    inlines = (PropertyImageInline,)


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ("title", "bot", "instructor_name", "price", "capacity", "enrolled_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "bot__name", "instructor_name")
    autocomplete_fields = ("tenant", "bot")


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    autocomplete_fields = ("product",)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("bot", "contact", "created_at")
    search_fields = ("bot__name",)
    autocomplete_fields = ("tenant", "bot", "contact")
    inlines = (CartItemInline,)


class BusinessOrderItemInline(admin.TabularInline):
    model = BusinessOrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "unit_price_minor", "currency", "quantity")
    autocomplete_fields = ("product",)


@admin.register(BusinessOrder)
class BusinessOrderAdmin(admin.ModelAdmin):
    list_display = ("public_id", "bot", "contact", "status", "subtotal", "created_at")
    list_filter = ("status",)
    search_fields = ("bot__name", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "bot", "contact")
    inlines = (BusinessOrderItemInline,)


@admin.register(TableReservation)
class TableReservationAdmin(admin.ModelAdmin):
    list_display = ("public_id", "bot", "contact", "party_size", "starts_at", "status")
    list_filter = ("status",)
    search_fields = ("bot__name", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "bot", "contact")
