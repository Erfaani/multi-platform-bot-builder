from django.contrib import admin
from django.utils.html import format_html

from apps.orders.models import Order, OrderEvent, OrderItem, Quote, QuoteItem


class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0
    readonly_fields = (
        "price_key",
        "label_key",
        "feature_slug",
        "price_version",
        "unit_amount_minor",
        "quantity",
        "amount_minor",
        "currency",
        "billing_kind",
    )

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "template",
        "tenant",
        "currency",
        "total_minor",
        "created_via",
        "expires_at",
        "created_at",
    )
    list_filter = ("created_via", "currency", "template")
    search_fields = ("public_id", "tenant__name", "created_by__email")
    readonly_fields = (
        "public_id",
        "session_secret",
        "platforms",
        "selected_features",
        "resolved_features",
        "business_draft",
        "subtotal_once_minor",
        "subtotal_recurring_minor",
        "total_minor",
    )
    inlines = (QuoteItemInline,)

    def has_add_permission(self, request) -> bool:
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "price_key",
        "label",
        "feature_slug",
        "price_version",
        "unit_amount_minor",
        "quantity",
        "amount_minor",
        "currency",
        "billing_kind",
        "snapshot",
    )

    # Frozen at purchase; editing would rewrite what the customer bought.
    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ("from_status", "to_status", "actor_type", "actor", "reason", "created_at")
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "tenant",
        "status_badge",
        "currency",
        "total_minor",
        "platforms",
        "placed_at",
    )
    list_filter = ("status", "currency", "template", "created_via")
    search_fields = ("number", "public_id", "tenant__name", "placed_by__email")
    date_hierarchy = "created_at"
    inlines = (OrderItemInline, OrderEventInline)
    readonly_fields = (
        "public_id",
        "number",
        "quote",
        "template",
        "platforms",
        "features",
        "business_snapshot",
        "currency",
        "subtotal_once_minor",
        "subtotal_recurring_minor",
        "total_minor",
        "placed_at",
        "paid_at",
        "activated_at",
        "cancelled_at",
        # `status` is deliberately read-only: it moves only through the state machine.
        "status",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: Order) -> str:
        colours = {
            "PAID": "#16a34a",
            "ACTIVE": "#16a34a",
            "PAYMENT_REJECTED": "#dc2626",
            "FAILED": "#dc2626",
            "CANCELLED": "#6b7280",
        }
        colour = colours.get(obj.status, "#2563eb")
        return format_html('<b style="color:{}">{}</b>', colour, obj.status)
