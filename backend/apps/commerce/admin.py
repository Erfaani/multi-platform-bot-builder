from django.contrib import admin

from apps.commerce.models import (
    BusinessOrder,
    BusinessOrderItem,
    Cart,
    CartItem,
    Product,
    ProductCategory,
    TableReservation,
)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "bot", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "bot", "category", "price", "stock", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot", "category")


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
