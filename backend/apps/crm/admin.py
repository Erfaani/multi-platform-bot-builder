from django.contrib import admin

from apps.crm.models import ContactNote, Feedback, Lead, Tag


class ContactNoteInline(admin.TabularInline):
    model = ContactNote
    extra = 0
    autocomplete_fields = ("author",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("public_id", "bot", "source", "status", "assigned_to", "created_at")
    list_filter = ("source", "status")
    search_fields = ("bot__name", "message", "phone", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "bot", "contact", "assigned_to")
    inlines = (ContactNoteInline,)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "bot")
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot")
    filter_horizontal = ("leads",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("bot", "contact", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("bot__name", "comment")
    autocomplete_fields = ("tenant", "bot", "contact")
