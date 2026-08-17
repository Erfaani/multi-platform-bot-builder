"""Tenant-scoped querysets.

``for_tenant()`` is the sanctioned read path and ``TenantScopedViewSet`` applies it
automatically. The default manager is deliberately *not* crippled: a manager that
refuses unscoped access breaks the admin, migrations and related descriptors, so
developers route around it and the control becomes decorative. See ADR-0005.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models

if TYPE_CHECKING:  # pragma: no cover
    from apps.customers.models import Tenant


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant: "Tenant | Any") -> "TenantQuerySet":
        """Restrict to a single tenant. Passing ``None`` yields nothing."""
        if tenant is None:
            return self.none()
        return self.filter(tenant=tenant)

    def for_tenants(self, tenants: list["Tenant"]) -> "TenantQuerySet":
        return self.filter(tenant__in=tenants)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):  # type: ignore[misc]
    use_in_migrations = False
