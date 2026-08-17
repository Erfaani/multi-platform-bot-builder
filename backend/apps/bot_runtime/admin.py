"""Runtime admin — the debugging surface when a customer says "my bot didn't reply"."""

from __future__ import annotations

from django.contrib import admin

from apps.bot_runtime.models import BotSession, BusinessContact, InboundUpdate, OutboundMessage


@admin.register(InboundUpdate)
class InboundUpdateAdmin(admin.ModelAdmin):
    list_display = ("platform_update_id", "instance", "status", "received_at", "processed_at")
    list_filter = ("status",)
    search_fields = ("platform_update_id", "instance__username")
    readonly_fields = tuple(field.name for field in InboundUpdate._meta.fields)
    date_hierarchy = "received_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("instance", "chat_ref", "status", "attempt", "sent_at", "next_attempt_at")
    list_filter = ("status", "is_bulk")
    search_fields = ("chat_ref", "instance__username", "error")
    readonly_fields = tuple(field.name for field in OutboundMessage._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(BusinessContact)
class BusinessContactAdmin(admin.ModelAdmin):
    """End users of customers' bots. Not platform accounts — they have no login."""

    list_display = ("display_name", "bot", "platform", "locale", "is_blocked", "last_seen_at")
    list_filter = ("platform", "is_blocked")
    search_fields = ("display_name", "username", "platform_user_id", "bot__name")
    readonly_fields = ("platform_user_id", "first_seen_at", "last_seen_at")


@admin.register(BotSession)
class BotSessionAdmin(admin.ModelAdmin):
    list_display = ("bot", "platform", "chat_ref", "state", "expires_at", "updated_at")
    list_filter = ("platform", "state")
    search_fields = ("chat_ref", "user_ref", "bot__name")
    readonly_fields = ("context",)
