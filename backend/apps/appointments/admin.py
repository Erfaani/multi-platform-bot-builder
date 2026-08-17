from django.contrib import admin

from apps.appointments.models import Appointment, AppointmentService, StaffMember, TimeOff


@admin.register(AppointmentService)
class AppointmentServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "bot", "duration_minutes", "price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot")


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "bot", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "bot__name")
    autocomplete_fields = ("tenant", "bot")
    filter_horizontal = ("services",)


@admin.register(TimeOff)
class TimeOffAdmin(admin.ModelAdmin):
    list_display = ("bot", "staff", "starts_at", "ends_at", "reason")
    search_fields = ("bot__name", "staff__name", "reason")
    autocomplete_fields = ("tenant", "bot", "staff")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("public_id", "bot", "service", "staff", "starts_at", "status")
    list_filter = ("status",)
    search_fields = ("bot__name", "service__name", "staff__name", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "bot", "contact", "service", "staff")
