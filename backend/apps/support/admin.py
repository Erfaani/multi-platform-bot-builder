from django.contrib import admin

from apps.support.models import SupportAttachment, SupportMessage, SupportTicket


class SupportAttachmentInline(admin.TabularInline):
    model = SupportAttachment
    extra = 0
    readonly_fields = ("original_filename", "content_type", "size_bytes", "sha256", "file")


class SupportMessageInline(admin.StackedInline):
    """Lets staff reply and leave internal notes directly from the ticket page."""

    model = SupportMessage
    extra = 1
    fields = ("author_type", "author", "body", "is_internal_note")
    autocomplete_fields = ("author",)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "tenant", "status", "priority", "assigned_to", "last_reply_at")
    list_filter = ("status", "priority")
    search_fields = ("subject", "tenant__name", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "bot", "created_by", "assigned_to")
    inlines = (SupportMessageInline,)


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author_type", "author", "is_internal_note", "created_at")
    list_filter = ("author_type", "is_internal_note")
    search_fields = ("ticket__subject", "body")
    autocomplete_fields = ("ticket", "author")
    inlines = (SupportAttachmentInline,)
