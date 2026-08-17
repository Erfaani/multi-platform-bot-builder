# Architecture review — Phase 0 sign-off

Date: 2026-08-10 · Reviewed: all Phase 0 documents · Outcome: **9 findings, all resolved**

A review of the Phase 0 deliverables before writing Phase 1 code. Two findings were genuine
self-contradictions, one was a control that read as strict but would have enforced nothing,
and the rest were gaps where one document referenced something another never defined.

---

### F-1 · Tenant resolution was undecidable — **contradiction**

`tenant_membership` lets a user belong to several tenants (spec §56: a receptionist working
at two clinics), but ADR-0005 and API.md both said the tenant is derived "from the
authenticated principal only" and that a request-supplied tenant is "always ignored". With
two memberships there is no answer.

**Resolved.** Split *selection* from *authority*: `X-Tenant: <tenant_public_id>` selects,
memberships authorize (a non-member gets 404, so the header can never grant access). One
membership → header optional. Several and no header → `409 tenant.ambiguous`.
Updated: ADR-0005, API.md §1, ARCHITECTURE.md §7.

### F-2 · The tenant-scoped default manager was unworkable — **bad control**

ADR-0005 layer 2 required `.unscoped()` for any unfiltered access. In practice a blocking
default manager breaks the Django admin, migrations, `dumpdata` and related-object
descriptors — so developers would scatter `.unscoped()` until the control meant nothing,
while the ADR still claimed strictness. A control that is routinely bypassed is worse than
one that never existed, because it stops people looking for a real one.

**Resolved.** Automatic filtering inside `TenantScopedViewSet.get_queryset()` (base class,
cannot be forgotten) plus a structural test asserting every viewset over a
`TenantOwnedModel` inherits it, plus the existing cross-tenant sweep. Weaker on paper,
considerably stronger in practice. ADR-0005 records the reversal.

### F-3 · `quote` violated its own tenancy rule — **contradiction**

The ERD showed `TENANT ||--o{ QUOTE` while the field list said `tenant_id NULL`, because the
builder must work before registration (spec §44).

**Resolved.** `Quote` is explicitly **not** a `TenantOwnedModel` — the single, documented
exception. It is owned by an unguessable `public_id` plus a session token until
`POST /quotes/{id}/claim/` binds it, after which `tenant_id` is immutable. Everything
downstream is tenant-owned normally.

### F-4 · Tables referenced but never defined — **gap**

`business_profile`, `working_hours`, `faq_entry`, `idempotency_record` and `system_setting`
were each used in API.md, I18N.md or the spec, and specified nowhere. `Idempotency-Key` was
a mandated header with no storage behind it.

**Resolved.** All added (DATABASE.md §8b, §8c), including the rule that a replay carrying a
*different* request fingerprint returns `409 idempotency.key_reused` rather than silently
replaying an unrelated response.

### F-5 · Feature manifests had no home — **gap**

ARCHITECTURE §5 defined a manifest object but never said where it lives, how it is
discovered, or how it reconciles with the `feature` table.

**Resolved.** Manifests live in the implementing app, discovered at app-ready by
`features.registry`. A Django system check fails startup when a manifest and its `Feature`
row disagree — silent drift would let a customer buy a feature the runtime cannot route.

### F-6 · Partitioning was asserted without a mechanism — **gap**

Django has no declarative partitioning, so "partitioned monthly" was aspirational, and
"30-day retention" is not achievable by dropping whole partitions.

**Resolved.** Documented as hand-written `RunSQL` migrations with a scheduled partition
maker/dropper, and the retention restated honestly as 30–60 days.

### F-7 · `bot.order_id` was misleading — **naming**

A bot outlives its first order; renewals and upgrades create more.
**Resolved.** Renamed `origin_order_id`.

### F-8 · `discount_minor` had no mechanism — **gap**

**Resolved.** Declared an admin-applied manual adjustment with `discount_reason` and an
audit entry. Coupons and campaigns are explicitly out of scope; the column keeps them
additive later.

### F-9 · `/healthz` was assumed by the Dockerfile — **gap**

`docker/backend.Dockerfile` health-checks `/healthz`, which nothing had committed to
building. Without it every backend container reports unhealthy from day one.
**Resolved.** `/healthz` and `/readyz` are now explicit Phase 1 deliverables.

### F-10 · Locale resolution ran before authentication — **found during Phase 1**

Added after the review, during implementation. `LocaleResolutionMiddleware` read
`request.user` to apply the user's saved locale, but Django middleware runs *before* DRF
authenticates, so every JWT-authenticated caller was still anonymous at that point. The
documented precedence (`?lang=` → **user preference** → cookie → `Accept-Language`) was
therefore unreachable for the entire API — a Persian user with `Accept-Language: en` got
English, silently.

This is the same mistake as F-1, in a second place: *deriving identity-dependent state in
middleware*. F-1 was caught in review because it was written down; this one was not,
because the middleware looked correct in isolation.

**Resolved.** Middleware now resolves everything except the user preference and records
`request.locale_source`; `LocaleAwareJWTAuthentication` applies the preference at the first
moment the user is known, and the middleware writes `Content-Language` afterwards from the
final value. An explicit `?lang=` still wins. Covered by
`tests/test_api_conventions.py::TestLocale` and verified end-to-end (a `fa` profile beats
`Accept-Language: en`).

**Generalisation for later phases:** nothing that depends on *who the caller is* may live
in middleware. That now covers tenant resolution (F-1) and locale (F-10); the same applies
to any future per-user quota, feature flag or audit context.

### F-11 · A broker outage broke checkout — **found during Phase 3**

Found by running the real flow, not by a test. `events.publish()` scheduled the outbox
relay in a `transaction.on_commit` hook, and `.delay()` raising on an unreachable Redis
propagated out of that hook — turning a **successful, already-committed order** into a
500 for the customer.

This inverted the entire point of the outbox pattern. The event is durably stored in the
database precisely so that delivery can fail independently; making the write depend on
the broker reintroduced exactly the coupling the pattern removes.

**Resolved.** `_schedule_relay` now logs and swallows enqueue failures — the message
stays `PENDING` and `sweep_pending_outbox` re-queues it. Verified live: with Redis down,
a payment approval completed, the order reached `PAID`, and the log read *"the periodic
sweep will retry it"*. Regression tests cover both the swallow and the sweep.

A second defect surfaced in the same incident: `.delay()` was contacting the **result
backend** before publishing, so a degraded Redis stalled the calling web request for
~75 seconds of retries before failing. Nothing in this system reads a task result, so
`task_ignore_result=True` is now set globally.

**Generalisation:** work committed to the database must never be undone — or reported as
failed — because a *downstream, retryable* delivery mechanism is unavailable. This applies
to every `on_commit` hook added from here on, including provisioning in Phase 4.

### F-12 · The provisioning saga skipped order states — **found during Phase 4**

The saga moved an order straight from `PROVISIONING` to `ACTIVE`. The state machine
refused it, which is exactly what an allow-list is for: `CONFIGURING` and `DEPLOYING` are
not decoration, they are what spec §20 shows the customer as progress
("Creating your bot → Configuring features → Activating bot").

**Resolved.** Each saga step now declares the order status it belongs to, and the runner
walks the order forward as it crosses phase boundaries. A retry additionally takes the
explicit `FAILED → PROVISIONING` edge, which exists for precisely that purpose — without
it every subsequent transition in a resumed job was illegal.

Worth noting that this was caught by the Phase 3 state machine catching Phase 4 code. The
allow-list paid for itself.

### F-13 · Feature entitlement inferred from route names — **found during Phase 4**

The router decided whether a bot had bought a feature by splitting the route name:
`business:contact` → feature `business`. But the feature slug is `contact`; `business` is
a UI grouping. Every core route was therefore silently denied, and the bot fell back to
the main menu instead of answering.

**Resolved.** Route ownership is now read from the feature manifests, which is where it
is actually declared. The lesson generalises: derive from declarations, not from string
conventions that happen to look parallel.

### F-14 · Encryption misconfiguration surfaced far too late — **found during Phase 4**

`.env.example` ships a placeholder `ENCRYPTION_KEK` that cannot decode — correct, since a
default that works is a default that reaches production. But the failure appeared as a
generic `ImproperlyConfigured` deep inside a service call, the first time anyone tried to
store a bot token.

**Resolved.** A Django system check (`core.E001`–`E003`) validates the key at startup with
the exact command to generate one, so it fails at `runserver` rather than at a customer's
first token submission. `.env.example` now says so at the field.

---

## Reconfirmed without change

The adapter/capability model, webhook-first runtime, immutable price versions, integer
minor-unit money with Toman as a display unit, envelope-encrypted credentials, the outbox
pattern, and the three-track provisioning strategy all survived review unchanged.

**Closed 2026-08-11:** ADR-0002 accepted — **both** provisioning tiers (bot pool and guided
token handoff) will be built. Phase 4 is unblocked. Remaining ADR-0002 items (token-custody
ToS review, pool username scheme) gate *shipping* to real customers, not building.
