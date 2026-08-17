# ADR-0005 — Tenant isolation: shared schema, defence in depth

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Tenant data includes a clinic's patient list and appointment history. A single forgotten
`.filter(tenant=…)` is a serious privacy breach, not a bug report. The design must survive
ordinary developer mistakes, because over a codebase this size the mistake **will** happen.

Options: database-per-tenant, schema-per-tenant, or shared schema with a tenant column.

## Decision

**Shared schema, tenant foreign key**, with four independent enforcement layers:

1. `TenantOwnedModel` — non-null `tenant` FK, composite indexes leading with `tenant_id`.
2. `TenantQuerySet.for_tenant(tenant)` is the only sanctioned read path, and
   **`TenantScopedViewSet` applies it automatically** in `get_queryset()`. Because it lives
   in the base class, it cannot be forgotten. A structural test asserts that every viewset
   registered over a `TenantOwnedModel` inherits from it.
3. The tenant is **selected** by the `X-Tenant` header and **authorized** from the
   principal's memberships (see §"Active tenant" below). A `tenant_id` in a request *body*
   is always ignored.
4. Object-level permission checks on detail routes; cross-tenant access returns **404**, not
   403 (403 confirms the object exists).

### Active tenant

A user may belong to several tenants (spec §56 — a receptionist can work at two clinics), so
"derive the tenant from the principal" is undecidable on its own. Resolution order:

1. `X-Tenant: <tenant_public_id>` header, **validated against the user's memberships** —
   a non-member gets 404, so the header selects but never grants.
2. If the user has exactly one membership, that tenant.
3. Otherwise `409 tenant.ambiguous`, listing the available tenants.

Selection comes from the request; authority never does. That distinction is the whole
control.

> **Revised 2026-08-10.** An earlier draft made the *default manager* refuse unscoped access,
> requiring an explicit `.unscoped()`. That was rejected on review: it breaks the Django
> admin, migrations, `dumpdata` and related-object descriptors, so developers would sprinkle
> `.unscoped()` everywhere to make things work — leaving a control that reads as strict and
> enforces nothing. Automatic scoping in the viewset base class is weaker on paper and much
> stronger in practice.

Plus an **automated proof**: `tests/security/test_cross_tenant.py` enumerates every route in
the DRF router, builds tenants A and B with a full object graph, and asserts tenant B gets
404 on all of A's `public_id`s across GET/PATCH/DELETE. A newly registered endpoint is
covered automatically — there is nothing for a developer to remember.

Phase 10 adds PostgreSQL **Row-Level Security** with a per-request `SET LOCAL app.tenant_id`,
so even hand-written SQL cannot cross tenants.

External identifiers are UUID `public_id`s, never sequential PKs, so IDs cannot be enumerated.

## Consequences

**Positive.** One migration history and one connection pool at thousands of tenants —
schema-per-tenant would mean thousands of schemas to migrate, and database-per-tenant
violates spec §58 outright. The automated sweep converts "remember to filter" from a review
habit into a build failure. RLS gives a second, independent line of defence.

**Negative.** Isolation is logical rather than physical, so a defect in layers 1–3 is a real
breach — which is precisely why layer 4 and RLS exist. Every tenant query must carry
`tenant_id`, and index design must lead with it. A tenant wanting physical isolation for
compliance cannot be served without a separate deployment; that is out of scope for v1 and
noted as a future enterprise option.
