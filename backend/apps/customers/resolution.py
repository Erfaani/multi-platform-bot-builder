"""Active-tenant resolution — the F-1 fix from docs/01-ARCHITECTURE-REVIEW.md.

Selection comes from the request (``X-Tenant``); authority comes from the caller's
memberships. The header chooses between tenants the user already belongs to and can
never grant access to one they do not. See ADR-0005.

This deliberately runs at the **view** layer, not in middleware: DRF performs JWT
authentication during view dispatch, so ``request.user`` in a middleware is still
anonymous for token-authenticated callers and every tenant lookup would silently fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.errors import TenantAccessDeniedError, TenantAmbiguousError
from apps.customers.models import Tenant, TenantMembership

HEADER = "HTTP_X_TENANT"
_CACHE_ATTR = "_resolved_tenant"


@dataclass(frozen=True, slots=True)
class ActiveTenant:
    tenant: Tenant
    membership: TenantMembership


def resolve_active_tenant(request) -> ActiveTenant:
    """Return the caller's active tenant, or raise.

    Fails closed: there is no "all tenants" fallback anywhere in this function.
    """
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise TenantAccessDeniedError()

    memberships = list(
        TenantMembership.objects.select_related("tenant").filter(
            user=user, tenant__status=Tenant.Status.ACTIVE
        )
    )
    if not memberships:
        raise TenantAccessDeniedError()

    requested = request.META.get(HEADER, "").strip()
    if requested:
        for membership in memberships:
            if str(membership.tenant.public_id) == requested:
                return _cache(request, membership)
        # A member of some tenant asked for one they do not belong to: 404, never 403.
        raise TenantAccessDeniedError()

    if len(memberships) == 1:
        return _cache(request, memberships[0])

    raise TenantAmbiguousError(
        details={
            "available_tenants": [
                {"id": str(m.tenant.public_id), "name": m.tenant.name, "role": m.role}
                for m in memberships
            ]
        }
    )


def _cache(request, membership: TenantMembership) -> ActiveTenant:
    from apps.core.request_context import set_active_tenant

    active = ActiveTenant(tenant=membership.tenant, membership=membership)
    setattr(request, _CACHE_ATTR, active)
    set_active_tenant(membership.tenant)
    return active


def optional_active_tenant(request) -> ActiveTenant | None:
    """Same resolution, but ``None`` instead of raising. For routes that adapt."""
    try:
        return resolve_active_tenant(request)
    except (TenantAccessDeniedError, TenantAmbiguousError):
        return None
