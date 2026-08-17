"""Active-tenant resolution — the F-1 fix (docs/01-ARCHITECTURE-REVIEW.md).

Selection comes from the request; authority comes from memberships.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.customers.models import Tenant, TenantMembership, TenantRole

pytestmark = pytest.mark.django_db


def _join(tenant: Tenant, user, role=TenantRole.MANAGER) -> TenantMembership:
    return TenantMembership.objects.create(
        tenant=tenant, user=user, role=role, accepted_at=timezone.now()
    )


class TestSingleMembership:
    def test_header_is_optional(self, auth_client, tenant_a):
        response = auth_client.get("/api/v1/tenants/active/")
        assert response.status_code == 200
        assert response.json()["id"] == str(tenant_a.public_id)

    def test_role_and_scopes_are_returned(self, auth_client, tenant_a):
        body = auth_client.get("/api/v1/tenants/active/").json()
        assert body["role"] == TenantRole.OWNER
        assert "*" in body["scopes"]


class TestMultipleMemberships:
    def test_omitting_the_header_is_a_409_not_a_silent_pick(
        self, auth_client, user, tenant_a, tenant_b
    ):
        """Guessing between workspaces would eventually write data to the wrong one."""
        _join(tenant_b, user)

        response = auth_client.get("/api/v1/tenants/active/")
        assert response.status_code == 409
        body = response.json()["error"]
        assert body["code"] == "tenant.ambiguous"
        assert len(body["details"]["available_tenants"]) == 2

    def test_header_selects_between_memberships(self, auth_client, user, tenant_a, tenant_b):
        _join(tenant_b, user)
        auth_client.credentials(
            HTTP_AUTHORIZATION=auth_client._credentials["HTTP_AUTHORIZATION"],
            HTTP_X_TENANT=str(tenant_b.public_id),
        )
        body = auth_client.get("/api/v1/tenants/active/").json()
        assert body["id"] == str(tenant_b.public_id)
        assert body["role"] == TenantRole.MANAGER


class TestNoMembership:
    def test_user_without_a_workspace_gets_404(self, auth_client, user):
        assert auth_client.get("/api/v1/tenants/active/").status_code == 404

    def test_suspended_tenant_is_not_resolvable(self, auth_client, tenant_a):
        tenant_a.status = Tenant.Status.SUSPENDED
        tenant_a.save(update_fields=["status"])
        assert auth_client.get("/api/v1/tenants/active/").status_code == 404


class TestTenantCreation:
    def test_creator_becomes_owner(self, auth_client, user):
        response = auth_client.post("/api/v1/tenants/", {"name": "New Clinic"}, format="json")
        assert response.status_code == 201
        assert response.json()["my_role"] == TenantRole.OWNER

    def test_slugs_do_not_collide(self, auth_client, user):
        first = auth_client.post("/api/v1/tenants/", {"name": "Clinic"}, format="json").json()
        second = auth_client.post("/api/v1/tenants/", {"name": "Clinic"}, format="json").json()
        assert first["slug"] != second["slug"]

    def test_blank_name_is_rejected(self, auth_client, user):
        assert (
            auth_client.post("/api/v1/tenants/", {"name": "   "}, format="json").status_code
            == 400
        )


class TestMemberManagement:
    def test_owner_can_add_a_member(self, auth_client, tenant_a, other_user):
        response = auth_client.post(
            f"/api/v1/tenants/{tenant_a.public_id}/members/",
            {"email": other_user.email, "role": TenantRole.STAFF},
            format="json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["outcome"] == "added"
        assert body["membership"]["role"] == TenantRole.STAFF

    def test_manager_cannot_add_members(self, api, tenant_a, other_user, user):
        """Members and billing stay with the owner (SECURITY.md §3)."""
        from apps.accounts.services import issue_tokens

        _join(tenant_a, other_user, role=TenantRole.MANAGER)
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(other_user)['access']}")

        response = api.post(
            f"/api/v1/tenants/{tenant_a.public_id}/members/",
            {"email": user.email, "role": TenantRole.STAFF},
            format="json",
        )
        assert response.status_code == 403

    def test_last_owner_cannot_be_removed(self, auth_client, tenant_a, user):
        """A workspace with no owner cannot be administered or billed."""
        membership = TenantMembership.objects.get(tenant=tenant_a, user=user)
        response = auth_client.delete(
            f"/api/v1/tenants/{tenant_a.public_id}/members/{membership.pk}/"
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "tenant.last_owner"


class TestRoleScopes:
    def test_staff_cannot_see_orders_or_billing(self, tenant_a, other_user):
        membership = _join(tenant_a, other_user, role=TenantRole.STAFF)
        assert membership.has_scope("appointments.manage")
        assert not membership.has_scope("orders.view")
        assert not membership.has_scope("members.manage")

    def test_owner_has_everything(self, tenant_a, user):
        membership = TenantMembership.objects.get(tenant=tenant_a, user=user)
        assert membership.has_scope("anything.at.all")
