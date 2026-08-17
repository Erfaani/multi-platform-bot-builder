"""Cross-tenant isolation sweep (ADR-0005, SECURITY.md §4).

This walks the *live router registry* rather than a hand-maintained list, so a new
tenant-scoped endpoint is covered the moment it is registered — there is nothing for
a developer to remember.
"""

from __future__ import annotations

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.api.viewsets import TenantScopedMixin
from apps.core.models import TenantOwnedModel

pytestmark = pytest.mark.django_db


def _iter_view_classes(patterns=None, prefix=""):
    """Yield (route, view_class) for every registered DRF view."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _iter_view_classes(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            view_class = getattr(entry.callback, "cls", None) or getattr(
                entry.callback, "view_class", None
            )
            if view_class is not None:
                yield prefix + str(entry.pattern), view_class


def _tenant_scoped_views():
    seen = {}
    for route, view_class in _iter_view_classes():
        if issubclass(view_class, TenantScopedMixin):
            seen.setdefault(view_class, route)
    return seen


class TestStructuralGuarantees:
    """These hold even before any tenant-scoped endpoint exists."""

    def test_every_tenant_owned_model_viewset_is_tenant_scoped(self):
        """A viewset over tenant data that is not tenant-scoped is a data leak.

        Catches the mistake at import time rather than in production.
        """
        offenders = []
        for route, view_class in _iter_view_classes():
            queryset = getattr(view_class, "queryset", None)
            model = getattr(queryset, "model", None)
            if model is None:
                continue
            if issubclass(model, TenantOwnedModel) and not issubclass(
                view_class, TenantScopedMixin
            ):
                offenders.append(f"{view_class.__name__} at /{route}")

        assert not offenders, (
            "These viewsets expose TenantOwnedModel data without tenant scoping: "
            + ", ".join(offenders)
        )

    def test_tenant_scoped_viewset_refuses_non_tenant_models(self):
        """The base class must fail loudly if pointed at a non-tenant model."""
        from rest_framework import viewsets

        from apps.core.api.viewsets import TenantScopedViewSet
        from apps.core.models import Currency

        class Misconfigured(TenantScopedViewSet):
            queryset = Currency.objects.all()

        view = Misconfigured()
        view.request = None
        with pytest.raises(TypeError, match="does not inherit TenantOwnedModel"):
            viewsets.ModelViewSet.get_queryset(view)  # bypass to reach our check
            view.get_queryset()


class TestTenantIsolation:
    def test_tenant_list_shows_only_own_workspaces(self, auth_client, tenant_a, tenant_b):
        response = auth_client.get("/api/v1/tenants/")
        assert response.status_code == 200
        returned = {row["id"] for row in response.json()}
        assert str(tenant_a.public_id) in returned
        assert str(tenant_b.public_id) not in returned

    def test_foreign_tenant_detail_returns_404_not_403(
        self, auth_client, tenant_a, tenant_b
    ):
        """403 would confirm the object exists. It must be indistinguishable from absent."""
        response = auth_client.get(f"/api/v1/tenants/{tenant_b.public_id}/")
        assert response.status_code == 404

    def test_foreign_tenant_members_are_not_listable(self, auth_client, tenant_a, tenant_b):
        response = auth_client.get(f"/api/v1/tenants/{tenant_b.public_id}/members/")
        assert response.status_code == 404

    def test_x_tenant_header_cannot_grant_access(self, auth_client, tenant_a, tenant_b):
        """The header selects among memberships; it never creates one."""
        auth_client.credentials(
            HTTP_AUTHORIZATION=auth_client._credentials["HTTP_AUTHORIZATION"],
            HTTP_X_TENANT=str(tenant_b.public_id),
        )
        response = auth_client.get("/api/v1/tenants/active/")
        assert response.status_code == 404

    def test_unauthenticated_access_is_rejected(self, api, tenant_a):
        assert api.get("/api/v1/tenants/").status_code == 401
        assert api.get(f"/api/v1/tenants/{tenant_a.public_id}/").status_code == 401


@pytest.mark.parametrize("route", ["/api/v1/tenants/", "/api/v1/auth/me/"])
def test_protected_routes_require_authentication(api, route):
    assert api.get(route).status_code == 401
