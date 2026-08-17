from django.contrib import admin

from apps.businesses.models import BusinessProfile, FaqEntry, WorkingHours


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "bot", "phone", "email", "city", "country")
    search_fields = ("display_name", "bot__name", "phone", "email")
    autocomplete_fields = ("bot",)


@admin.register(FaqEntry)
class FaqEntryAdmin(admin.ModelAdmin):
    list_display = ("question", "bot", "is_active", "source", "sort_order")
    list_filter = ("is_active", "source")
    search_fields = ("question", "answer", "bot__name")
    autocomplete_fields = ("bot",)


@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ("bot", "weekday", "opens_at", "closes_at", "is_closed")
    list_filter = ("weekday", "is_closed")
    autocomplete_fields = ("bot",)
