from django.contrib import admin

from apps.core.formatting import invalidate_currency_cache
from apps.core.models import Currency, FailedTaskLog, IdempotencyRecord, OutboxMessage, SystemSetting


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "exponent", "display_unit", "display_divisor", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        invalidate_currency_cache()


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "is_public", "updated_at")
    list_filter = ("is_public",)
    search_fields = ("key", "description")

    def save_model(self, request, obj, form, change) -> None:
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(OutboxMessage)
class OutboxMessageAdmin(admin.ModelAdmin):
    list_display = ("event_type", "status", "occurred_at", "attempts", "published_at")
    list_filter = ("status", "event_type")
    readonly_fields = ("event_type", "payload", "occurred_at", "published_at", "attempts")
    search_fields = ("event_type", "public_id")

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ("endpoint", "key", "status", "response_status", "expires_at")
    list_filter = ("status",)
    search_fields = ("key", "endpoint")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(FailedTaskLog)
class FailedTaskLogAdmin(admin.ModelAdmin):
    list_display = ("task_name", "exception_type", "created_at", "request_id")
    list_filter = ("task_name", "exception_type")
    search_fields = ("task_name", "task_id", "request_id", "exception_message")
    readonly_fields = (
        "task_name",
        "task_id",
        "args",
        "kwargs",
        "exception_type",
        "exception_message",
        "traceback",
        "request_id",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
