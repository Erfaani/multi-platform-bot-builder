"""Team invitations (spec §26): inviting a colleague who has no account yet."""

from __future__ import annotations

import re

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import User
from apps.core.errors import ConflictError, PermissionDeniedError, ValidationError
from apps.customers.models import TenantInvitation, TenantMembership, TenantRole
from apps.customers.services import (
    accept_invitation,
    get_invitation_preview,
    invite_or_add_member,
    revoke_invitation,
)

pytestmark = pytest.mark.django_db

INVITEE_EMAIL = "colleague@example.com"


def _token_from_outbox() -> str:
    body = mail.outbox[-1].body
    match = re.search(r"/invite/([^\s]+)", body)
    assert match, body
    return match.group(1)


def _invitee() -> User:
    """A brand-new account matching the invited address — the person accepting."""
    return User.objects.create_user(
        email=INVITEE_EMAIL, password="TestPassw0rd!23", email_verified_at=timezone.now()
    )


class TestInviteOrAddMember:
    def test_an_existing_account_is_added_directly(self, tenant_a, user, other_user):
        outcome, result = invite_or_add_member(
            tenant=tenant_a, actor=user, email=other_user.email, role=TenantRole.STAFF
        )
        assert outcome == "added"
        assert isinstance(result, TenantMembership)
        assert not mail.outbox

    def test_an_unknown_email_gets_invited_instead(self, tenant_a, user):
        outcome, result = invite_or_add_member(
            tenant=tenant_a, actor=user, email="new-hire@example.com", role=TenantRole.STAFF
        )
        assert outcome == "invited"
        assert isinstance(result, TenantInvitation)
        assert result.token_hash  # the raw token is never stored
        assert len(mail.outbox) == 1
        assert "new-hire@example.com" in mail.outbox[0].to

    def test_a_second_invite_to_the_same_email_refreshes_rather_than_duplicates(
        self, tenant_a, user
    ):
        invite_or_add_member(tenant=tenant_a, actor=user, email="new-hire@example.com")
        invite_or_add_member(tenant=tenant_a, actor=user, email="new-hire@example.com")

        assert TenantInvitation.objects.filter(
            tenant=tenant_a, email="new-hire@example.com", revoked_at__isnull=True
        ).count() == 1

    def test_a_non_manager_cannot_invite(self, tenant_a, other_user):
        TenantMembership.objects.create(
            tenant=tenant_a, user=other_user, role=TenantRole.STAFF, accepted_at=timezone.now()
        )
        with pytest.raises(PermissionDeniedError):
            invite_or_add_member(tenant=tenant_a, actor=other_user, email="x@example.com")

    def test_cannot_invite_someone_already_a_member(self, tenant_a, user, other_user):
        TenantMembership.objects.create(
            tenant=tenant_a, user=other_user, role=TenantRole.STAFF, accepted_at=timezone.now()
        )
        with pytest.raises(ConflictError):
            invite_or_add_member(tenant=tenant_a, actor=user, email=other_user.email)


class TestAcceptInvitation:
    def test_accepting_creates_the_membership(self, tenant_a, user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()
        invitee = _invitee()

        membership = accept_invitation(raw_token=token, user=invitee)

        assert membership.tenant_id == tenant_a.pk
        assert membership.user_id == invitee.pk

    def test_accepting_with_a_different_email_is_rejected(self, tenant_a, user, other_user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()

        with pytest.raises(ValidationError):
            accept_invitation(raw_token=token, user=other_user)

    def test_an_unknown_token_is_rejected(self, tenant_a, other_user):
        with pytest.raises(ValidationError):
            accept_invitation(raw_token="not-a-real-token", user=other_user)

    def test_a_revoked_invitation_cannot_be_accepted(self, tenant_a, user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()
        invitee = _invitee()
        invitation = TenantInvitation.objects.get(tenant=tenant_a, email=INVITEE_EMAIL)

        revoke_invitation(tenant=tenant_a, actor=user, invitation=invitation)

        with pytest.raises(ValidationError):
            accept_invitation(raw_token=token, user=invitee)

    def test_accepting_twice_is_idempotent(self, tenant_a, user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()
        invitee = _invitee()

        first = accept_invitation(raw_token=token, user=invitee)
        second = accept_invitation(raw_token=token, user=invitee)
        assert first.pk == second.pk

    def test_preview_shows_the_workspace_without_consuming_the_token(self, tenant_a, user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()
        invitee = _invitee()

        preview = get_invitation_preview(token)
        assert preview.tenant_id == tenant_a.pk

        # Still usable afterwards — a preview is read-only.
        accept_invitation(raw_token=token, user=invitee)


class TestInvitationApi:
    def test_add_member_by_unknown_email_returns_invited(self, auth_client, tenant_a):
        response = auth_client.post(
            f"/api/v1/tenants/{tenant_a.public_id}/members/",
            {"email": "new-hire@example.com", "role": TenantRole.STAFF},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["outcome"] == "invited"

    def test_pending_invitations_are_listable_and_revocable(self, auth_client, tenant_a):
        auth_client.post(
            f"/api/v1/tenants/{tenant_a.public_id}/members/",
            {"email": "new-hire@example.com", "role": TenantRole.STAFF},
            format="json",
        )
        listed = auth_client.get(f"/api/v1/tenants/{tenant_a.public_id}/invitations/")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        invitation_id = listed.json()[0]["id"]

        revoked = auth_client.delete(
            f"/api/v1/tenants/{tenant_a.public_id}/invitations/{invitation_id}/"
        )
        assert revoked.status_code == 204

        listed_again = auth_client.get(f"/api/v1/tenants/{tenant_a.public_id}/invitations/")
        assert listed_again.json() == []

    def test_preview_and_accept_end_to_end(self, auth_client, tenant_a):
        auth_client.post(
            f"/api/v1/tenants/{tenant_a.public_id}/members/",
            {"email": INVITEE_EMAIL, "role": TenantRole.STAFF},
            format="json",
        )
        token = _token_from_outbox()
        invitee = _invitee()

        from apps.accounts.services import issue_tokens
        from rest_framework.test import APIClient

        invitee_client = APIClient()
        invitee_client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(invitee)['access']}")

        preview = invitee_client.post("/api/v1/invitations/preview/", {"token": token}, format="json")
        assert preview.status_code == 200
        assert preview.json()["tenant_name"] == tenant_a.name

        accepted = invitee_client.post("/api/v1/invitations/accept/", {"token": token}, format="json")
        assert accepted.status_code == 200

        assert TenantMembership.objects.filter(tenant=tenant_a, user=invitee).exists()

    def test_preview_requires_no_authentication(self, api, tenant_a, user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()

        response = api.post("/api/v1/invitations/preview/", {"token": token}, format="json")
        assert response.status_code == 200

    def test_accept_requires_authentication(self, api, tenant_a, user):
        invite_or_add_member(tenant=tenant_a, actor=user, email=INVITEE_EMAIL)
        token = _token_from_outbox()

        response = api.post("/api/v1/invitations/accept/", {"token": token}, format="json")
        assert response.status_code == 401
