"""PostgreSQL Row-Level Security — defence-in-depth for tenant isolation (Phase 10;
ADR-0005 §"Phase 10 adds PostgreSQL Row-Level Security").

Application-level scoping (`TenantOwnedModel` + `TenantScopedViewSet.get_queryset()`,
ADR-0005) is the primary defence and stays exactly as it is — this is a second,
independent layer so that even a bug in application code, a hand-written management
command, or raw SQL run against the database cannot read or write another tenant's row.

**Why a second role is required, not just `ENABLE`/`FORCE ROW LEVEL SECURITY`:**
PostgreSQL policies are unconditionally bypassed by a superuser or any role with the
`BYPASSRLS` attribute — `FORCE ROW LEVEL SECURITY` does not change this, it only affects
whether the *table owner* is exempt. The role this project's `DATABASE_URL` connects as
is the same role that owns every table (it ran the migrations), so without a second,
deliberately unprivileged role, "enabling RLS" would be a no-op for the very connection
that needs it. `botbuilder_app` is that role: `NOLOGIN` (nothing can authenticate as it
directly), `NOSUPERUSER`, `NOBYPASSRLS`, granted only `SELECT`/`INSERT`/`UPDATE`/`DELETE` —
never table ownership or DDL. The migrating user is made a member of it (`GRANT ... TO
CURRENT_USER`) so the running application can drop into it for the lifetime of a request
via `SET ROLE botbuilder_app` (see `apps.core.tenant_session`) without a second password or
a second `DATABASE_URL`. Migrations themselves never issue `SET ROLE`, so they keep full
owner privileges regardless of this role's existence.

**The policy.** Every tenant-owned table gets `USING`/`WITH CHECK`
`tenant_id = current_setting('app.tenant_id', true)::bigint` — `NULLIF(..., '')` first, so
an unset or blank session variable compares against `NULL` (never true against any real
`tenant_id`), which is what makes an unscoped connection fail *closed*: it sees zero rows
rather than everything. `apps.core.tenant_session` is what actually sets `app.tenant_id`
per request; a raw `psql` session, a management command, or a background worker that never
sets it (and never `SET ROLE`s into `botbuilder_app`) is unaffected — this migration adds
the mechanism, it does not on its own change what the Django app's own connection can see
today (see settings' `DATABASE_APP_ROLE`, opt-in, for why).
"""

from __future__ import annotations

from django.db import migrations

#: Every table currently backing a `TenantOwnedModel` subclass, as of this migration —
#: a snapshot, exactly like every other migration's field list. A future tenant-owned
#: model needs its own migration adding it here; nothing enforces that automatically
#: (the same is true of Django's own migration model, which is also a snapshot).
TENANT_TABLES: tuple[str, ...] = (
    "ai_configuration",
    "ai_knowledge_chunk",
    "ai_knowledge_document",
    "ai_usage_record",
    "analytics_event",
    "appointment",
    "appointment_service",
    "bot",
    "business_contact",
    "business_order",
    "business_profile",
    "cart",
    "crm_contact_note",
    "crm_feedback",
    "crm_lead",
    "crm_tag",
    "faq_entry",
    "order",
    "product",
    "product_category",
    "staff_member",
    "subscription",
    "support_ticket",
    "table_reservation",
    "time_off",
    "working_hours",
)

APP_ROLE = "botbuilder_app"

_ENABLE_ROLE_SQL = f"""
DO $do$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$do$;

GRANT {APP_ROLE} TO CURRENT_USER;

GRANT USAGE ON SCHEMA public TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {APP_ROLE};
"""

_DISABLE_ROLE_SQL = f"""
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM {APP_ROLE};
REVOKE USAGE ON SCHEMA public FROM {APP_ROLE};
-- The role itself is left in place (empty of privileges) rather than dropped: another
-- session may currently hold it via `SET ROLE`, and `DROP ROLE` requires no live
-- dependencies. A permission-less role left behind is harmless.
"""


def _enable_policy(table: str) -> str:
    # Quoted: several of these names (`order`) are reserved SQL keywords.
    return f"""
ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON "{table}"
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);
"""


def _disable_policy(table: str) -> str:
    return f"""
DROP POLICY IF EXISTS tenant_isolation ON "{table}";
ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("ai", "0001_initial"),
        ("analytics", "0001_initial"),
        ("appointments", "0001_initial"),
        ("bots", "0001_initial"),
        ("bot_runtime", "0002_initial"),
        ("businesses", "0002_businessprofile_working_hours_text"),
        ("commerce", "0001_initial"),
        ("crm", "0001_initial"),
        ("orders", "0006_alter_order_status"),
        ("subscriptions", "0001_initial"),
        ("support", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=_ENABLE_ROLE_SQL, reverse_sql=_DISABLE_ROLE_SQL),
        *[
            migrations.RunSQL(sql=_enable_policy(table), reverse_sql=_disable_policy(table))
            for table in TENANT_TABLES
        ],
    ]
