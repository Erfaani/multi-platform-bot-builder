from django.contrib import admin

from apps.customers.models import (
    ChannelIdentity,
    IdentityLinkNonce,
    Tenant,
    TenantInvitation,
    TenantMembership,
)


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    fk_name = "tenant"
    extra = 0
    autocomplete_fields = ("user", "invited_by")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "country", "default_locale", "default_currency", "created_at")
    list_filter = ("status", "country", "default_locale", "default_currency")
    search_fields = ("name", "slug", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    inlines = (TenantMembershipInline,)


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "role", "accepted_at", "created_at")
    list_filter = ("role",)
    search_fields = ("tenant__name", "user__email")
    autocomplete_fields = ("tenant", "user", "invited_by")


@admin.register(TenantInvitation)
class TenantInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "role", "invited_by", "expires_at", "accepted_at", "revoked_at")
    list_filter = ("role",)
    search_fields = ("email", "tenant__name")
    readonly_fields = ("token_hash",)
    autocomplete_fields = ("tenant", "invited_by")

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(ChannelIdentity)
class ChannelIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "platform_user_id", "username", "linked_at")
    list_filter = ("platform",)
    search_fields = ("user__email", "platform_user_id", "username")
    autocomplete_fields = ("user",)


@admin.register(IdentityLinkNonce)
class IdentityLinkNonceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "expires_at", "consumed_at", "created_at")
    list_filter = ("platform",)
    readonly_fields = ("nonce",)
    search_fields = ("user__email",)

    def has_add_permission(self, request) -> bool:
        return False
