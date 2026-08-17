"""Serializers validate shape; business rules live in services (ARCHITECTURE.md §2)."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=12, max_length=128)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    preferred_locale = serializers.ChoiceField(
        choices=settings.ACTIVE_LOCALES, required=False, default=settings.LANGUAGE_CODE
    )
    preferred_currency = serializers.ChoiceField(
        choices=settings.ACTIVE_CURRENCIES, required=False, default=settings.DEFAULT_CURRENCY
    )
    country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    timezone = serializers.CharField(required=False, default="UTC", max_length=64)

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    access_expires_in = serializers.IntegerField(read_only=True)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TenantMembershipSummarySerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField(source="tenant.public_id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    role = serializers.CharField(read_only=True)


class UserSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    full_name = serializers.CharField(read_only=True)
    is_email_verified = serializers.BooleanField(read_only=True)
    memberships = TenantMembershipSummarySerializer(many=True, read_only=True)
    staff_scopes = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "preferred_locale",
            "preferred_currency",
            "country",
            "timezone",
            "is_email_verified",
            "memberships",
            "staff_scopes",
            "created_at",
        )
        read_only_fields = ("email", "created_at")

    def get_staff_scopes(self, obj: User) -> list[str]:
        from apps.accounts.services import user_scopes

        return sorted(user_scopes(obj))


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField()
