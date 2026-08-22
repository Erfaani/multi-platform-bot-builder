"""Tenant use cases."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from apps.customers.models import (
    ChannelIdentity,
    IdentityLinkNonce,
    Tenant,
    TenantInvitation,
    TenantMembership,
    TenantRole,
)

logger = logging.getLogger(__name__)

INVITATION_TTL = timedelta(days=7)
LINK_CODE_TTL = timedelta(minutes=10)
LINK_CODE_LENGTH = 6


def _unique_slug(name: str) -> str:
    base = slugify(name)[:48] or "workspace"
    candidate, suffix = base, 1
    while Tenant.objects.filter(slug=candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"[:64]
    return candidate


@transaction.atomic
def create_tenant(
    *,
    owner: User,
    name: str,
    country: str = "",
    default_locale: str | None = None,
    default_currency: str | None = None,
    timezone_name: str | None = None,
) -> Tenant:
    """Create a workspace and make ``owner`` its OWNER."""
    if not name.strip():
        raise ValidationError(field_errors={"name": ["A workspace name is required."]})

    tenant = Tenant.objects.create(
        name=name.strip(),
        slug=_unique_slug(name),
        country=(country or owner.country).upper()[:2],
        default_locale=default_locale or owner.preferred_locale,
        default_currency=default_currency or owner.preferred_currency,
        timezone=timezone_name or owner.timezone,
        created_by=owner,
    )
    TenantMembership.objects.create(
        tenant=tenant, user=owner, role=TenantRole.OWNER, accepted_at=timezone.now()
    )
    record_audit(
        actor=owner,
        action="tenant.created",
        resource_type="tenant",
        resource_id=str(tenant.public_id),
        tenant=tenant,
    )
    return tenant


@transaction.atomic
def add_member(
    *, tenant: Tenant, actor: User, user: User, role: str = TenantRole.STAFF
) -> TenantMembership:
    actor_membership = TenantMembership.objects.filter(tenant=tenant, user=actor).first()
    if actor_membership is None or not actor_membership.has_scope("members.manage"):
        raise PermissionDeniedError(code="tenant.cannot_manage_members")

    if TenantMembership.objects.filter(tenant=tenant, user=user).exists():
        raise ConflictError(
            code="tenant.already_member", message="This person is already in the workspace."
        )

    membership = TenantMembership.objects.create(
        tenant=tenant, user=user, role=role, invited_by=actor
    )
    record_audit(
        actor=actor,
        action="tenant.member_added",
        resource_type="tenant_membership",
        resource_id=str(membership.pk),
        tenant=tenant,
        metadata={"role": role, "user": str(user.public_id)},
    )
    return membership


@transaction.atomic
def remove_member(*, tenant: Tenant, actor: User, membership: TenantMembership) -> None:
    actor_membership = TenantMembership.objects.filter(tenant=tenant, user=actor).first()
    if actor_membership is None or not actor_membership.has_scope("members.manage"):
        raise PermissionDeniedError(code="tenant.cannot_manage_members")

    if membership.role == TenantRole.OWNER:
        remaining_owners = (
            TenantMembership.objects.filter(tenant=tenant, role=TenantRole.OWNER)
            .exclude(pk=membership.pk)
            .count()
        )
        if remaining_owners == 0:
            # A workspace without an owner cannot be administered or billed.
            raise ConflictError(
                code="tenant.last_owner",
                message="A workspace must keep at least one owner.",
            )

    user_public_id = str(membership.user.public_id)
    membership.delete()
    record_audit(
        actor=actor,
        action="tenant.member_removed",
        resource_type="tenant_membership",
        resource_id=user_public_id,
        tenant=tenant,
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_member_management(tenant: Tenant, actor: User) -> None:
    membership = TenantMembership.objects.filter(tenant=tenant, user=actor).first()
    if membership is None or not membership.has_scope("members.manage"):
        raise PermissionDeniedError(code="tenant.cannot_manage_members")


@transaction.atomic
def invite_or_add_member(
    *, tenant: Tenant, actor: User, email: str, role: str = TenantRole.STAFF
) -> tuple[str, TenantMembership | TenantInvitation]:
    """Add someone to the workspace, by account if they have one, by email if not.

    Returns ``("added", membership)`` or ``("invited", invitation)`` so the caller can
    shape the response (and the audit trail) around what actually happened.
    """
    _require_member_management(tenant, actor)
    email = email.strip().lower()

    existing_user = User.objects.filter(email=email).first()
    if existing_user is not None:
        return "added", add_member(tenant=tenant, actor=actor, user=existing_user, role=role)

    if TenantMembership.objects.filter(tenant=tenant, user__email=email).exists():
        raise ConflictError(
            code="tenant.already_member", message="This person is already in the workspace."
        )

    raw_token = secrets.token_urlsafe(32)
    invitation, _ = TenantInvitation.objects.update_or_create(
        tenant=tenant,
        email=email,
        accepted_at=None,
        revoked_at=None,
        defaults={
            "role": role,
            "token_hash": _hash_token(raw_token),
            "invited_by": actor,
            "expires_at": timezone.now() + INVITATION_TTL,
        },
    )

    _send_invitation_email(invitation=invitation, raw_token=raw_token, inviter=actor)

    record_audit(
        actor=actor,
        action="tenant.member_invited",
        resource_type="tenant_invitation",
        resource_id=str(invitation.pk),
        tenant=tenant,
        metadata={"email": email, "role": role},
    )
    return "invited", invitation


def _send_invitation_email(*, invitation: TenantInvitation, raw_token: str, inviter: User) -> None:
    """Direct `send_mail`, not the `Notification` model.

    A `Notification` is addressed to an existing platform user (`recipient` is a
    required FK); an invitee has no account yet, so there is nothing for it to point at.
    """
    link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/invite/{raw_token}"
    try:
        send_mail(
            subject=f"You've been invited to join {invitation.tenant.name}",
            message=(
                f"{inviter.full_name} invited you to join {invitation.tenant.name} "
                f"on Bot Builder Platform.\n\nAccept the invitation: {link}\n\n"
                "This link expires in 7 days."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
    except Exception:
        # The invitation row exists regardless; it can be resent from the dashboard.
        # A mail-server hiccup must not turn into a 500 for the person sending it.
        logger.warning("Could not send invitation email to %s", invitation.email, exc_info=True)


def list_pending_invitations(tenant: Tenant) -> list[TenantInvitation]:
    return list(
        TenantInvitation.objects.filter(
            tenant=tenant, accepted_at__isnull=True, revoked_at__isnull=True
        ).order_by("-created_at")
    )


@transaction.atomic
def revoke_invitation(*, tenant: Tenant, actor: User, invitation: TenantInvitation) -> None:
    _require_member_management(tenant, actor)
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at", "updated_at"])
    record_audit(
        actor=actor,
        action="tenant.invitation_revoked",
        resource_type="tenant_invitation",
        resource_id=str(invitation.pk),
        tenant=tenant,
    )


@transaction.atomic
def accept_invitation(*, raw_token: str, user: User) -> TenantMembership:
    """Consume an invitation token and create the membership.

    Deliberately does not check who sent it or match names — the token itself, held by
    whoever clicked the emailed link, is the entire authorization (same shape as email
    verification in `apps.accounts.services`).
    """
    invitation = (
        TenantInvitation.objects.select_for_update()
        .filter(token_hash=_hash_token(raw_token))
        .first()
    )
    if invitation is None:
        raise ValidationError(
            code="tenant.invalid_invitation",
            message="This invitation is invalid or has expired.",
        )

    if invitation.email != user.email.lower():
        # The link was for a specific address; accepting it as someone else would let
        # an intercepted email add an unrelated account to the workspace.
        raise ValidationError(
            code="tenant.invitation_email_mismatch",
            message="This invitation was sent to a different email address.",
        )

    # Checked before `is_usable`: accepting sets `accepted_at`, which makes the
    # invitation itself no longer "usable" — so a second click on the same link (or a
    # retried request) must be resolved here, or it would be rejected as expired.
    existing = TenantMembership.objects.filter(tenant=invitation.tenant, user=user).first()
    if existing is not None:
        if invitation.accepted_at is None:
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["accepted_at", "updated_at"])
        return existing

    if not invitation.is_usable:
        raise ValidationError(
            code="tenant.invalid_invitation",
            message="This invitation is invalid or has expired.",
        )

    membership = TenantMembership.objects.create(
        tenant=invitation.tenant,
        user=user,
        role=invitation.role,
        invited_by=invitation.invited_by,
        accepted_at=timezone.now(),
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at", "updated_at"])

    record_audit(
        actor=user,
        action="tenant.invitation_accepted",
        resource_type="tenant_membership",
        resource_id=str(membership.pk),
        tenant=invitation.tenant,
    )
    return membership


def get_invitation_preview(raw_token: str) -> TenantInvitation:
    """Read-only lookup so the accept page can show *which* workspace before login."""
    invitation = TenantInvitation.objects.select_related("tenant").filter(
        token_hash=_hash_token(raw_token)
    ).first()
    if invitation is None or not invitation.is_usable:
        raise NotFoundError(
            code="tenant.invalid_invitation", message="This invitation is invalid or has expired."
        )
    return invitation


# --------------------------------------------------------------------------- channel linking (spec §47)


def _generate_link_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(LINK_CODE_LENGTH))


@transaction.atomic
def create_link_code(*, user: User, platform: str, request_ip: str | None = None) -> IdentityLinkNonce:
    """A short, human-typeable code, not the model's own UUID default.

    Chosen over a `/start <uuid>` deep link (ADR-pending): identical UX on Telegram and
    Bale, no per-platform deep-link handling to build. Any code the user already had
    outstanding for this platform is invalidated first, so only the one just shown on
    the dashboard can ever be typed successfully.
    """
    IdentityLinkNonce.objects.filter(
        user=user, platform=platform, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())

    for _ in range(5):
        try:
            return IdentityLinkNonce.objects.create(
                nonce=_generate_link_code(),
                user=user,
                platform=platform,
                expires_at=timezone.now() + LINK_CODE_TTL,
                created_ip=request_ip,
            )
        except IntegrityError:
            continue
    raise ConflictError(
        code="customers.link_code_exhausted", message="Could not generate a code. Please try again."
    )


def list_channel_identities(user: User) -> list[ChannelIdentity]:
    return list(ChannelIdentity.objects.filter(user=user).order_by("platform"))


@transaction.atomic
def unlink_channel_identity(*, user: User, identity_id: int) -> None:
    identity = ChannelIdentity.objects.filter(user=user, pk=identity_id).first()
    if identity is None:
        raise NotFoundError()

    identity.delete()
    record_audit(
        actor=user,
        action="customers.channel_unlinked",
        resource_type="channel_identity",
        resource_id=str(identity_id),
        metadata={"platform": identity.platform},
    )


@transaction.atomic
def consume_link_code(
    *, code: str, platform: str, platform_user_id: str, username: str = ""
) -> ChannelIdentity | None:
    """Redeem a code sent to the bot. Returns `None` for any invalid/expired/reused code
    — deliberately not an error, since the caller (a bot handler) always shows the same
    generic rejection either way rather than confirming which codes ever existed."""
    nonce = (
        IdentityLinkNonce.objects.select_for_update()
        .filter(nonce=code, platform=platform)
        .first()
    )
    if nonce is None or not nonce.is_usable:
        return None

    nonce.consumed_at = timezone.now()
    nonce.save(update_fields=["consumed_at"])

    identity, _ = ChannelIdentity.objects.update_or_create(
        platform=platform,
        platform_user_id=platform_user_id,
        defaults={"user": nonce.user, "username": username, "linked_at": timezone.now()},
    )
    record_audit(
        actor=nonce.user,
        action="customers.channel_linked",
        resource_type="channel_identity",
        resource_id=str(identity.pk),
        metadata={"platform": platform},
    )
    return identity


def resolve_tenant_membership(
    *, platform: str, platform_user_id: str, tenant_id: int
) -> TenantMembership | None:
    """Is the platform account behind this message a member of this tenant?

    Used by the bot's owner-admin menu to decide whether to show it at all — never by
    anything that touches money or a customer's own data, which stay behind the
    website's ordinary session auth regardless of who messages the bot.
    """
    identity = (
        ChannelIdentity.objects.filter(platform=platform, platform_user_id=platform_user_id)
        .select_related("user")
        .first()
    )
    if identity is None:
        return None
    return TenantMembership.objects.filter(tenant_id=tenant_id, user=identity.user).first()
