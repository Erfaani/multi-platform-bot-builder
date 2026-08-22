"""Chat-native ordering support (Phase 10.5's cold-start counterpart to the website
builder): account bootstrap and order-status lookup for a customer who is ordering a
brand-new bot by chatting with the platform's own builder bot, with no prior website
account.
"""

from __future__ import annotations

import secrets

from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.accounts.models import User
from apps.accounts.services import register_user
from apps.audit.services import record_audit
from apps.core.errors import ConflictError
from apps.customers.models import ChannelIdentity, Tenant
from apps.customers.services import create_tenant
from apps.orders.models import Order


def is_valid_email(text: str) -> bool:
    try:
        validate_email(text.strip())
    except DjangoValidationError:
        return False
    return True


def find_or_bootstrap_account(
    *, email: str, platform: str, platform_user_id: str, username: str = "", locale: str = "en"
) -> User:
    """Resolve the website account this chat order belongs to.

    Deliberately refuses to attach an order to an EXISTING account just because someone
    typed its email — that would be an account-takeover vector (SECURITY.md §2, the same
    rule `apps.customers.services.consume_link_code` already enforces for cross-channel
    linking). An email already on file raises `ConflictError` so the caller can point the
    customer at `/link` instead. A brand-new account gets a random password the customer
    never sees or types — their proven identity for this whole flow is the live chat
    session itself, not a credential; a website password can be set later if they want
    dashboard access via that route too.
    """
    email = email.strip().lower()
    if User.objects.filter(email=email).exists():
        raise ConflictError(
            code="bot_builder.email_taken",
            message="An account already exists for that email.",
        )

    user = register_user(
        email=email, password=secrets.token_urlsafe(32), preferred_locale=locale
    )

    ChannelIdentity.objects.update_or_create(
        platform=platform,
        platform_user_id=platform_user_id,
        defaults={"user": user, "username": username},
    )
    record_audit(
        actor=user,
        action="bot_builder.account_bootstrapped",
        resource_type="user",
        resource_id=str(user.public_id),
        metadata={"platform": platform},
    )
    return user


def start_tenant_for_chat_order(*, user: User, business_name: str) -> Tenant:
    return create_tenant(owner=user, name=business_name.strip() or "My business")


def most_recent_order_for_platform_user(*, platform: str, platform_user_id: str) -> Order | None:
    """For the `/status` command — a pull-based alternative to a push notification once
    staff approve payment (Telegram/Bale delivery in `apps.notifications` is not wired
    up yet; see that app's `deliver_notification`). The customer checks back with the
    same builder bot rather than needing an email or a dashboard visit."""
    identity = (
        ChannelIdentity.objects.filter(platform=platform, platform_user_id=platform_user_id)
        .select_related("user")
        .first()
    )
    if identity is None:
        return None

    return (
        Order.objects.filter(tenant__memberships__user=identity.user)
        .select_related("template")
        .order_by("-created_at")
        .first()
    )
