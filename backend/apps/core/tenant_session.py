"""Per-request PostgreSQL session state for Row-Level Security (Phase 10; see
`apps/core/migrations/0002_row_level_security.py` for the policies this drives).

Two independent knobs, both opt-in via settings so local dev and the test suite are
unaffected unless explicitly configured:

- `settings.DATABASE_APP_ROLE` — if set, every new physical connection immediately drops
  from the migrating role's privileges into it via `SET ROLE`, for that connection's
  lifetime. Unset (the local/test default) means the app keeps running as the same
  superuser role that owns the tables — RLS policies exist but are bypassed, exactly as
  PostgreSQL always bypasses RLS for a superuser or table owner. This is not a bug in this
  module; it is why the role exists at all (see the migration's docstring).
- The active tenant, set via `set_current_tenant(tenant)` — called from
  `TenantScopedMixin.initial()` (`apps/core/api/viewsets.py`) — issues
  `SELECT set_config('app.tenant_id', ...)` on the current connection and updates
  `apps.core.request_context`'s existing contextvar in the same call, so both layers agree
  on "the current tenant" from one call site.

Both are reset at the end of every request (`request_finished`) — necessary because Django
reuses pooled connections (`CONN_MAX_AGE`) across requests; without an explicit reset, one
request's tenant (or dropped role) would leak into the next request that happens to land on
the same connection.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import request_finished
from django.db import connection
from django.db.backends.signals import connection_created

from apps.core.request_context import get_active_tenant, set_active_tenant

_ROLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _app_role() -> str:
    role = getattr(settings, "DATABASE_APP_ROLE", "") or ""
    if role and not _ROLE_NAME_RE.fullmatch(role):
        # SET ROLE takes an identifier, not a bind parameter — refuse anything that isn't
        # unambiguously a plain role name rather than interpolating it unchecked.
        raise ImproperlyConfigured(f"DATABASE_APP_ROLE={role!r} is not a valid role name.")
    return role


def _drop_privileges(sender, connection, **kwargs) -> None:
    role = _app_role()
    if not role or connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {role}")


def set_current_tenant(tenant) -> None:
    """Scope both the in-process contextvar and (on Postgres) the RLS session variable."""
    set_active_tenant(tenant)
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        if tenant is None:
            cursor.execute("RESET app.tenant_id")
        else:
            cursor.execute("SELECT set_config('app.tenant_id', %s, false)", [str(tenant.pk)])


def _reset_session(sender, **kwargs) -> None:
    """Clear the tenant scope a pooled connection (`CONN_MAX_AGE`) would otherwise carry
    into the next, unrelated request.

    Deliberately does *not* `RESET ROLE`: the privilege drop in `_drop_privileges` is
    connection-lifetime, done once on `connection_created`, which does not fire again for
    a connection Django is reusing — a `RESET ROLE` here would revert a reused connection
    to full owner privileges for every request after the first, silently bypassing RLS.

    Also skips the round trip entirely when this request never called
    `set_current_tenant()` in the first place (`/healthz`, `/metrics`, any view outside
    `TenantScopedMixin`) — otherwise a pooled connection left open by an *earlier*,
    unrelated request would make even a deliberately DB-free view like `/healthz` pay for
    a DB write it has nothing to do with, defeating the whole point of a liveness check
    that must not depend on the database (`apps.core.health`).
    """
    had_tenant = get_active_tenant() is not None
    set_active_tenant(None)
    if not had_tenant or connection.vendor != "postgresql" or connection.connection is None:
        return
    with connection.cursor() as cursor:
        cursor.execute("RESET app.tenant_id")


def register() -> None:
    connection_created.connect(_drop_privileges, dispatch_uid="tenant_session.drop_privileges")
    request_finished.connect(_reset_session, dispatch_uid="tenant_session.reset_session")
