"""Account use cases.

Views call these; they own their transactions. Token issuance is funnelled through
``issue_tokens()`` so phone OTP / Telegram Login / social can be added later without
touching the API layer (spec §7).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import EmailVerificationToken, User
from apps.audit.services import record_audit
from apps.core.errors import ConflictError, ValidationError

EMAIL_TOKEN_TTL = timedelta(hours=24)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_tokens(user: User) -> dict[str, Any]:
    """Mint an access/refresh pair.

    The single place tokens are created — every future auth method funnels here.
    """
    refresh = RefreshToken.for_user(user)
    refresh["locale"] = user.preferred_locale
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "access_expires_in": int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
    }


@transaction.atomic
def register_user(
    *,
    email: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    preferred_locale: str | None = None,
    preferred_currency: str | None = None,
    country: str = "",
    timezone_name: str = "UTC",
    ip: str | None = None,
) -> User:
    email = email.strip().lower()
    if User.objects.filter(email=email).exists():
        # Deliberately explicit: registration cannot be silent about a taken address,
        # but login failures stay generic (SECURITY.md §2).
        raise ConflictError(code="accounts.email_taken", message="This email is already registered.")

    locale = preferred_locale if preferred_locale in settings.ACTIVE_LOCALES else settings.LANGUAGE_CODE
    currency = (
        preferred_currency
        if preferred_currency in settings.ACTIVE_CURRENCIES
        else settings.DEFAULT_CURRENCY
    )

    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        preferred_locale=locale,
        preferred_currency=currency,
        country=country.upper()[:2],
        timezone=timezone_name,
    )
    create_email_verification_token(user)
    record_audit(
        actor=user, action="user.registered", resource_type="user", resource_id=str(user.public_id), ip=ip
    )
    return user


def create_email_verification_token(user: User) -> str:
    raw = secrets.token_urlsafe(32)
    EmailVerificationToken.objects.create(
        user=user, token_hash=_hash_token(raw), expires_at=timezone.now() + EMAIL_TOKEN_TTL
    )
    # Phase 3 wires this to the notification service; console backend in the meantime.
    return raw


@transaction.atomic
def verify_email(*, raw_token: str) -> User:
    token = (
        EmailVerificationToken.objects.select_for_update()
        .filter(token_hash=_hash_token(raw_token), consumed_at__isnull=True)
        .first()
    )
    if token is None or not token.is_usable:
        raise ValidationError(
            code="accounts.invalid_token", message="This verification link is invalid or expired."
        )
    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])

    user = token.user
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at", "updated_at"])
    record_audit(
        actor=user, action="user.email_verified", resource_type="user", resource_id=str(user.public_id)
    )
    return user


@transaction.atomic
def update_profile(*, user: User, **fields: Any) -> User:
    allowed = {
        "first_name",
        "last_name",
        "phone",
        "preferred_locale",
        "preferred_currency",
        "country",
        "timezone",
    }
    changed: list[str] = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "preferred_locale" and value not in settings.ACTIVE_LOCALES:
            raise ValidationError(
                code="accounts.unsupported_locale", field_errors={"preferred_locale": ["Unsupported locale."]}
            )
        if key == "preferred_currency" and value not in settings.ACTIVE_CURRENCIES:
            raise ValidationError(
                code="accounts.unsupported_currency",
                field_errors={"preferred_currency": ["Unsupported currency."]},
            )
        setattr(user, key, value)
        changed.append(key)

    if changed:
        user.save(update_fields=[*changed, "updated_at"])
        record_audit(
            actor=user,
            action="user.profile_updated",
            resource_type="user",
            resource_id=str(user.public_id),
            metadata={"fields": changed},
        )
    return user


def user_scopes(user: User) -> set[str]:
    """Effective platform-staff scopes for a user."""
    if user.is_superuser:
        return {"*"}
    scopes: set[str] = set()
    for assignment in user.staff_roles.all():
        scopes |= assignment.scopes
    return scopes


def has_scope(user: User, scope: str) -> bool:
    scopes = user_scopes(user)
    return "*" in scopes or scope in scopes
