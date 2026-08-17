from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import EmailVerificationToken, User, UserStaffRole


class UserStaffRoleInline(admin.TabularInline):
    model = UserStaffRole
    fk_name = "user"
    extra = 0
    autocomplete_fields = ("granted_by",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "full_name", "preferred_locale", "is_active", "is_staff", "created_at")
    list_filter = ("is_active", "is_staff", "is_superuser", "preferred_locale")
    search_fields = ("email", "first_name", "last_name", "phone")
    readonly_fields = ("public_id", "created_at", "updated_at", "last_login", "last_login_ip")
    inlines = (UserStaffRoleInline,)

    fieldsets = (
        (None, {"fields": ("email", "password", "public_id")}),
        (_("Personal"), {"fields": ("first_name", "last_name", "phone", "phone_verified_at")}),
        (
            _("Localization"),
            {"fields": ("preferred_locale", "preferred_currency", "country", "timezone")},
        ),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Audit"), {"fields": ("email_verified_at", "last_login", "last_login_ip", "created_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )


@admin.register(UserStaffRole)
class UserStaffRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "granted_by", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email",)
    autocomplete_fields = ("user", "granted_by")


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "expires_at", "consumed_at", "created_at")
    readonly_fields = ("token_hash",)
    search_fields = ("user__email",)

    def has_add_permission(self, request) -> bool:
        return False
