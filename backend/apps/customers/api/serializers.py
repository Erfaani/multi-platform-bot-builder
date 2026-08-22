from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.customers.models import (
    ChannelIdentity,
    IdentityLinkNonce,
    Tenant,
    TenantInvitation,
    TenantMembership,
    TenantRole,
)


class TenantSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "status",
            "country",
            "default_locale",
            "default_currency",
            "timezone",
            "my_role",
            "created_at",
        )
        read_only_fields = ("slug", "status", "created_at")

    def get_my_role(self, obj: Tenant) -> str | None:
        roles = self.context.get("roles_by_tenant_id", {})
        return roles.get(obj.pk)


class TenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    country = serializers.CharField(max_length=2, required=False, allow_blank=True)
    default_locale = serializers.ChoiceField(choices=settings.ACTIVE_LOCALES, required=False)
    default_currency = serializers.ChoiceField(choices=settings.ACTIVE_CURRENCIES, required=False)
    timezone = serializers.CharField(max_length=64, required=False)


class TenantMembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.public_id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    scopes = serializers.SerializerMethodField()

    class Meta:
        model = TenantMembership
        fields = (
            "id",
            "user_id",
            "email",
            "full_name",
            "role",
            "scopes",
            "accepted_at",
            "created_at",
        )
        read_only_fields = fields

    def get_scopes(self, obj: TenantMembership) -> list[str]:
        return sorted(obj.scopes)


class AddMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=TenantRole.choices, default=TenantRole.STAFF)


class AddMemberResultSerializer(serializers.Serializer):
    """Shape depends on whether the email matched an existing account."""

    outcome = serializers.ChoiceField(choices=("added", "invited"))
    membership = TenantMembershipSerializer(required=False)
    invitation_email = serializers.EmailField(required=False)


class TenantInvitationSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    invited_by_email = serializers.EmailField(source="invited_by.email", read_only=True)

    class Meta:
        model = TenantInvitation
        fields = ("id", "email", "role", "invited_by_email", "expires_at", "created_at")
        read_only_fields = fields


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField()


class InvitationPreviewSerializer(serializers.Serializer):
    tenant_name = serializers.CharField()
    role = serializers.CharField()
    email = serializers.EmailField()


class ChannelIdentitySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChannelIdentity
        fields = ("id", "platform", "username", "linked_at")
        read_only_fields = fields


class ChannelLinkRequestSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=ChannelIdentity.Platform.choices)


class ChannelLinkCodeSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="nonce", read_only=True)

    class Meta:
        model = IdentityLinkNonce
        fields = ("code", "platform", "expires_at")
        read_only_fields = fields
