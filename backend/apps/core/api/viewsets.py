"""Tenant-scoped API base classes.

The filtering happens in ``get_queryset()`` on the base class, so a developer writing
a new tenant resource cannot forget it. That is the whole control — see ADR-0005 and
the F-2 finding in docs/01-ARCHITECTURE-REVIEW.md.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from rest_framework import viewsets

from apps.core.models import TenantOwnedModel


class TenantScopedMixin:
    """Restricts every queryset to the request's active tenant.

    `initial()` — not `get_queryset()` — is where the PostgreSQL RLS session variable
    (`apps.core.tenant_session`, Phase 10) gets set: DRF calls `initial()` for *every*
    action including a bare `create`, which never calls `get_queryset()` at all. RLS is a
    second, independent layer underneath the `.for_tenant()` filtering below (ADR-0005) —
    it must be armed before the first query of the request, not only before a list query.
    """

    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def initial(self, request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]

        from apps.core.tenant_session import set_current_tenant

        set_current_tenant(self.get_tenant())

    def get_tenant(self):
        """The caller's active tenant. Raises rather than falling back."""
        from apps.customers.resolution import resolve_active_tenant

        return resolve_active_tenant(self.request).tenant

    def get_membership(self):
        from apps.customers.resolution import resolve_active_tenant

        return resolve_active_tenant(self.request).membership

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()  # type: ignore[misc]
        model = queryset.model
        if not issubclass(model, TenantOwnedModel):
            raise TypeError(
                f"{type(self).__name__} is tenant-scoped but {model.__name__} "
                "does not inherit TenantOwnedModel."
            )
        return queryset.for_tenant(self.get_tenant())

    def perform_create(self, serializer: Any) -> None:
        # The tenant is never taken from request data (ADR-0005 layer 3).
        serializer.save(tenant=self.get_tenant())


class TenantScopedViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    """Full CRUD over a tenant-owned resource."""


class TenantScopedReadOnlyViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only access to a tenant-owned resource."""
