"""Tenants and membership.

A ``Tenant`` is the customer organisation that owns bots, orders and business data.
Users reach a tenant through a ``TenantMembership``; a user may belong to several
(spec §56), which is why the active tenant must be selected explicitly — see ADR-0005.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TimeStampedModel


class Tenant(PublicIdModel, TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        SUSPENDED = "SUSPENDED", _("Suspended")
        CLOSED = "CLOSED", _("Closed")

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    country = models.CharField(max_length=2, blank=True)
    default_locale = models.CharField(max_length=8, default="en")
    default_currency = CurrencyCodeField(default="USD")
    timezone = models.CharField(max_length=64, default="UTC")

    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "tenant"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class TenantRole(models.TextChoices):
    """Roles inside a customer organisation (spec §56)."""

    OWNER = "OWNER", _("Owner")
    MANAGER = "MANAGER", _("Manager")
    STAFF = "STAFF", _("Staff")


#: What each tenant role may do. A clinic receptionist (STAFF) can work the calendar
#: but must not see orders, payments or team management.
TENANT_ROLE_SCOPES: dict[str, set[str]] = {
    TenantRole.OWNER: {"*"},
    TenantRole.MANAGER: {
        "bots.view",
        "bots.manage",
        "business.manage",
        "appointments.view",
        "appointments.manage",
        "commerce.manage",
        "crm.view",
        "crm.manage",
        "analytics.view",
        "support.manage",
        "ai.manage",
    },
    TenantRole.STAFF: {
        "bots.view",
        "appointments.view",
        "appointments.manage",
        "crm.view",
    },
}


class TenantMembership(TimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=TenantRole.choices, default=TenantRole.STAFF)
    extra_permissions = models.JSONField(
        default=list, blank=True, help_text=_("Additional scopes granted beyond the role.")
    )
    invited_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenant_membership"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="tenant_membership_uniq")
        ]
        indexes = [models.Index(fields=["user", "tenant"], name="membership_user_tenant_idx")]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.tenant_id} ({self.role})"

    @property
    def scopes(self) -> set[str]:
        return TENANT_ROLE_SCOPES.get(self.role, set()) | set(self.extra_permissions or [])

    def has_scope(self, scope: str) -> bool:
        scopes = self.scopes
        return "*" in scopes or scope in scopes


class TenantInvitation(TimeStampedModel):
    """An invite to someone without an account yet (spec §56 "owner may invite staff").

    `add_member` handles the case where the invitee already has an account; this model
    exists for the other one — a raw email address with nothing behind it yet. Accepting
    consumes the token and creates the membership at that point, whether the person
    registers fresh or was already logged in under that address.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=TenantRole.choices, default=TenantRole.STAFF)

    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenant_invitation"
        constraints = [
            # One outstanding invitation per address per workspace — resending replaces
            # it rather than piling up duplicates a customer has to sort through.
            models.UniqueConstraint(
                fields=["tenant", "email"],
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="tenant_invitation_pending_uniq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.tenant_id} ({self.role})"

    @property
    def is_usable(self) -> bool:
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )


class ChannelIdentity(TimeStampedModel):
    """Links a platform account to a user, for cross-channel continuity (spec §47).

    Created only by consuming a single-use nonce — never by matching a phone number
    or email, which would be an account-takeover path (SECURITY.md §2).
    """

    class Platform(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        BALE = "bale", "Bale"

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="channel_identities"
    )
    platform = models.CharField(max_length=16, choices=Platform.choices)
    platform_user_id = models.CharField(max_length=64)
    username = models.CharField(max_length=64, blank=True)
    linked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "channel_identity"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "platform_user_id"], name="channel_identity_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.platform}:{self.platform_user_id}"


class IdentityLinkNonce(TimeStampedModel):
    """Short-lived, single-use code backing the ``/start <nonce>`` deep link."""

    nonce = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="link_nonces"
    )
    platform = models.CharField(max_length=16, choices=ChannelIdentity.Platform.choices)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "identity_link_nonce"

    @property
    def is_usable(self) -> bool:
        return self.consumed_at is None and self.expires_at > timezone.now()
