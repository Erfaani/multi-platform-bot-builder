# API

Status: **Phase 0 — contract design** · Django REST Framework · Last updated: 2026-08-10

Base: `/api/v1/`. OpenAPI schema is generated (`drf-spectacular`) and served at
`/api/v1/schema/` with Swagger UI at `/api/v1/docs/`.

---

## 1. Conventions

- **Resource identifiers in URLs are `public_id` UUIDs**, never sequential PKs.
- `Accept-Language` sets the response locale; falls back to the user's `preferred_locale`,
  then the platform default. All customer-facing messages are localized.
- **`X-Quote-Session: <secret>`** authenticates an *anonymous* builder quote. Returned once
  by `POST /quotes/`, never included in later representations. A quote's `public_id` alone
  is deliberately insufficient — otherwise a shared or guessed link would expose a business
  draft. Once a quote is claimed by a workspace the secret stops working and tenant
  membership governs access instead.
- **`X-Tenant: <tenant_public_id>`** selects the active tenant on every tenant-scoped route.
  It is validated against the caller's memberships — it selects, it never grants. Omit it
  when the user belongs to exactly one tenant; omitting it with several returns
  `409 tenant.ambiguous` listing the options. A `tenant_id` in a request body is always
  ignored. See [ADR-0005](docs/adr/0005-tenant-isolation.md).
- Pagination: cursor-based for feeds/logs, page-number for admin tables.
  `?page=`, `?page_size=` (max 100) / `?cursor=`.
- Filtering `?field=value`, search `?search=`, ordering `?ordering=-created_at`.
- Idempotency: `Idempotency-Key` header **required** on `POST /orders/`,
  `POST /payments/`, and any provisioning trigger. Replays return the original response.
- Rate limits: anonymous 60/min, authenticated 600/min, auth endpoints 10/min,
  upload endpoints 20/hour. Headers `X-RateLimit-*` and `Retry-After` on 429.
- Money is always rendered as an object, never a bare number:

```json
{ "amount_minor": 14900, "currency": "USD", "formatted": "$149.00" }
```

### Error format (uniform, spec §57)

```json
{
  "error": {
    "code": "order.invalid_transition",
    "message": "This order can no longer be modified.",
    "details": { "from": "PAID", "to": "DRAFT" },
    "field_errors": { "platforms": ["This field is required."] },
    "trace_id": "01J8ZQ7K3M9P"
  }
}
```

`message` is localized and safe to show a customer. `trace_id` correlates to server logs.
Stack traces are never returned. HTTP status: 400 validation, 401 unauthenticated,
403 forbidden, 404 not found **or cross-tenant**, 409 conflict/state, 422 business rule,
429 throttled, 503 maintenance.

> Cross-tenant access returns **404, not 403** — a 403 confirms the object exists.

---

## 2. Authentication — `/api/v1/auth/`

| Method | Path | Purpose |
|---|---|---|
| POST | `register/` | email + password + locale + country |
| POST | `login/` | → access (15 min) + refresh (14 d, rotating) |
| POST | `refresh/` | rotate refresh, blacklist old |
| POST | `logout/` | blacklist refresh |
| POST | `password/reset/` · `password/reset/confirm/` | reset flow |
| POST | `email/verify/` | verification |
| GET  | `me/` · PATCH `me/` | profile, locale, currency, timezone |
| POST | `link/nonce/` | issue a single-use deep-link nonce (§47) |
| POST | `link/consume/` | *internal, service-auth only* — builder bots redeem a nonce |

Extensible for phone OTP / Telegram Login / social (spec §7) — the token issuance path is
already abstracted behind `accounts.services.issue_tokens()`.

---

## 3. Public catalogue (unauthenticated, cached)

| Method | Path | Purpose |
|---|---|---|
| GET | `templates/` · `templates/{slug}/` | business templates + their default/required features |
| GET | `features/` · `features/{slug}/` | feature catalogue with per-platform availability |
| GET | `platforms/` | sellable platforms + whether capabilities are verified |
| GET | `currencies/` | active currencies + formatting metadata |
| GET | `settings/public/` | brand, locales, currencies, maintenance flag |

All are localized by `Accept-Language` / `?lang=`. `features/` returns a `platforms` map
per feature (`{available, reason, note}`) so the builder disables an option rather than
letting the customer discover the problem at the price step.

> `preview` never appears in `platforms/` — it is a rendering target, not a sellable channel.

---

## 4. Builder, quotes & pricing

| Method | Path | Purpose |
|---|---|---|
| POST | `quotes/` | create and price a quote (anonymous allowed) |
| GET | `quotes/{public_id}/` | read it back — this is what makes §18 omnichannel work |
| PUT | `quotes/{public_id}/` | re-price as the configuration changes |
| GET/POST | `quotes/{public_id}/preview/` | render the bot preview (§48) via `PreviewAdapter` |
| POST | `quotes/{public_id}/claim/` | attach an anonymous quote to the caller's workspace |

Request — note that **no amount is ever sent by the client**:

```json
{
  "template": "clinic",
  "platforms": ["telegram", "bale"],
  "features": ["appointment", "faq"],
  "currency": "USD",
  "country": "IR",
  "business": { "name": "Tehran Smile Clinic" }
}
```

Response (abridged):

```json
{
  "id": "…", "currency": "USD",
  "selected_features": ["appointment", "faq"],
  "resolved_features": ["business_profile", "working_hours", "appointment", "faq"],
  "auto_added_features": ["working_hours"],
  "items": [
    { "price_key": "template.clinic.base",      "label": "Medical clinic setup", "amount": {…}, "billing_kind": "ONE_TIME" },
    { "price_key": "platform.telegram.base",    "label": "Telegram",             "amount": {…}, "billing_kind": "ONE_TIME" },
    { "price_key": "platform.multi.surcharge",  "label": "Multi-platform setup", "amount": {…}, "billing_kind": "ONE_TIME", "quantity": 1 },
    { "price_key": "feature.appointment.setup", "label": "Appointment booking",  "amount": {…}, "billing_kind": "ONE_TIME" },
    { "price_key": "hosting.standard.monthly",  "label": "Hosting (monthly)",    "amount": {…}, "billing_kind": "RECURRING_MONTHLY" }
  ],
  "subtotal_once": {…}, "subtotal_recurring": {…}, "total": {…},
  "expires_at": "2026-08-17T10:00:00Z",
  "session_secret": "…"
}
```

**Only one platform base appears**, plus a surcharge per additional channel — spec §9,
never `base × platforms`. The primary channel is the most expensive one, so the total does
not depend on the order the customer ticked the boxes.

`session_secret` is returned **only** on creation. `total` is what is due now
(setup + first recurring period).

Prices come from live `price_version` rows only, and are frozen into `quote_item` rows the
moment the quote is produced. The frontend never computes a total. A price list missing a
required key returns `409 pricing.incomplete` rather than quoting a wrong number.

Selecting a feature a chosen platform cannot run returns
`400 quote.feature_unavailable_on_platform` with a `conflicts` list naming the feature,
platform and missing capability.

---

## 5. Orders — `/api/v1/orders/`

| Method | Path | Purpose |
|---|---|---|
| POST | `orders/` | place an order from a claimed quote |
| GET | `orders/` | list (tenant-scoped) |
| GET | `orders/{public_id}/` | detail + items + events + latest payment |
| POST | `orders/{public_id}/cancel/` | only from pre-`PAID` states |

Customers **cannot** set `status`. There is no PATCH: the resource is read-only plus
explicit actions, and every move goes through the state machine.

Each order carries **`available_actions`** — the states reachable *by this customer* from
where the order is now, derived from the allow-list in `orders/domain/state_machine.py`.
The UI renders buttons from it rather than hard-coding which are visible, so the server
stays the single source of truth. `PAID` never appears there.

Re-posting the same `quote` returns the **existing** order rather than creating a second
one, so a double-clicked checkout button cannot double-charge. (An `Idempotency-Key`
header is accepted for the generic case and backed by `idempotency_record`; for this
endpoint the quote itself is the natural idempotency key.)

---

## 6. Payments — `/api/v1/payments/`

| Method | Path | Purpose |
|---|---|---|
| GET | `orders/{order_public_id}/payment-methods/` | methods usable for **this** order |
| POST | `payments/` | start a payment against an order |
| POST | `payments/{public_id}/proof/` | multipart: receipt file and/or `tx_hash` |
| GET | `payments/{public_id}/` | status, instructions, proof requirements |

Payment methods are listed **per order**, not globally: currency and minimum amount decide
what is genuinely offerable, and a global list would show options that fail at the next
step. A method whose currency differs from the order's is rejected — amounts are never
converted (spec §13).

A payment response carries the provider's `instructions` (headline, labelled fields, notes,
and a `copyable` value for a one-tap copy button) plus a `proof` block stating whether a
file, a `tx_hash`, or both are required. **The client does not decide this** — the provider
does, so adding a gateway later changes no frontend logic.

`internal_note` is never serialized: staff notes about a customer must not reach that
customer. `config` on a payment method is likewise never exposed raw; only the provider's
rendered instructions are.

Receipt uploads run the full validation pipeline ([SECURITY.md](SECURITY.md) §7) and return
`400 upload.*` on rejection. A receipt image already seen on another order is **flagged for
review, not blocked** — a customer who legitimately paid twice with one transfer would
otherwise be stranded. A `tx_hash` already used anywhere returns
`409 payment.tx_hash_already_used`: one blockchain payment cannot settle two orders.

---

## 7. Bots & business data — `/api/v1/bots/`

| Method | Path | Purpose |
|---|---|---|
| GET | `bots/` · `bots/{public_id}/` | list/detail — name, platforms, status, username, link, features |
| PATCH | `bots/{public_id}/configuration/` | welcome message, menu, branding, locale, timezone |
| GET/PATCH | `bots/{public_id}/business-profile/` | name, description, logo, phone, address, hours |
| GET | `bots/{public_id}/features/` | enabled features + editable config |
| PATCH | `bots/{public_id}/features/{slug}/` | per-feature configuration |
| GET | `bots/{public_id}/health/` | webhook status, last update, error counters |

`bot_credential` has **no endpoint**. There is no code path that returns a token to any
client, staff included.

Feature data, all tenant- and bot-scoped:

```
bots/{id}/appointments/            services/  staff/  working-hours/  slots/
bots/{id}/products/                categories/
bots/{id}/business-orders/
bots/{id}/contacts/                leads/  notes/  tags/
bots/{id}/faq/
bots/{id}/analytics/summary/       analytics/timeseries/
bots/{id}/ai/knowledge/            ai/settings/
```

---

## 8. Dashboard, notifications, support, subscriptions

```
GET   dashboard/summary/            counts, revenue, recent activity
GET   notifications/                PATCH notifications/{id}/read/   POST notifications/read-all/
GET   subscriptions/                GET subscriptions/{id}/
POST  support/tickets/              GET support/tickets/  GET/POST support/tickets/{id}/messages/
```

---

## 9. Admin — `/api/v1/admin/`

Requires a staff role; each route declares the minimum role (spec §55).

| Path | Min role |
|---|---|
| `admin/dashboard/` | ADMIN |
| `admin/customers/`, `admin/customers/{id}/` | SUPPORT_AGENT |
| `admin/orders/`, `admin/orders/{id}/transition/` | ADMIN |
| `admin/payments/`, `admin/payments/{id}/approve/`, `/reject/` | FINANCE_AGENT |
| `admin/payments/{id}/receipt-url/` | FINANCE_AGENT (signed URL, 5 min TTL, audited) |
| `admin/payment-methods/` (CRUD) | FINANCE_AGENT |
| `admin/features/`, `admin/templates/` (CRUD) | ADMIN |
| `admin/prices/` (create version, close version) | ADMIN |
| `admin/currencies/` | ADMIN |
| `admin/bots/`, `admin/bots/{id}/suspend/`, `/resume/` | BOT_OPS_AGENT |
| `admin/provisioning/jobs/`, `/{id}/retry/` | BOT_OPS_AGENT |
| `admin/bot-pool/` | BOT_OPS_AGENT |
| `admin/translations/` | ADMIN |
| `admin/subscriptions/{id}/extend/`, `/suspend/` | FINANCE_AGENT |
| `admin/audit-logs/`, `admin/system/health/` | SUPER_ADMIN |

`admin/prices/` is create-and-close only — **no update, no delete**. That is what protects
historical orders.

---

## 10. Webhooks (not part of the public API)

```
POST /webhooks/telegram/{bot_public_id}/
POST /webhooks/bale/{bot_public_id}/
```

Unauthenticated by JWT; authenticated by per-bot secret (header token where the platform
supports it, otherwise HMAC over the raw body). Constant-time comparison. The handler
persists and enqueues only — no business logic, no external calls. Always returns `200`
once the update is durably stored, so the platform never retries a message we already have.

Detail: [BOT_RUNTIME.md](BOT_RUNTIME.md).

---

## 11. Service-to-service

The Telegram and Bale **builder bots** are first-party clients of this same API. They
authenticate with a service credential plus an acting-user context derived from a linked
`channel_identity`. They get **no** private endpoints and **no** ability to bypass tenancy —
this is what keeps spec §45/§46 from duplicating order logic.
