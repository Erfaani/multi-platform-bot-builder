from django.contrib import admin

from apps.notifications.models import Notification, NotificationDelivery


class DeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    readonly_fields = ("channel", "status", "attempts", "error", "sent_at")
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("event_type", "recipient", "tenant", "read_at", "created_at")
    list_filter = ("event_type",)
    search_fields = ("recipient__email", "tenant__name", "event_type")
    readonly_fields = ("public_id", "params")
    inlines = (DeliveryInline,)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False
