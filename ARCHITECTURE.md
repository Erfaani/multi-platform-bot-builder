# ARCHITECTURE

Status: **Phase 0 — Accepted** · Last updated: 2026-08-10

Read [docs/00-ANALYSIS.md](docs/00-ANALYSIS.md) first; it explains *why* several of these
decisions differ from the original specification.

---

## 1. Style

**Modular monolith.** One deployable Django project, hard internal boundaries, no
microservices. Boundaries are enforced by convention plus an import-linter contract, so any
app can later be extracted without rewriting callers.

```
                              Internet
                                 │
                    ┌────────────┴────────────┐
                    │           Nginx         │
                    └──┬──────────────────┬───┘
                       │                  │
        /api/*, /webhooks/*          Next.js (SSR/static)
                       │
              ┌────────▼─────────┐
              │  Django + DRF    │   (gunicorn/uvicorn, stateless, N replicas)
              └───┬──────────┬───┘
                  │          │
        ┌─────────▼──┐   ┌───▼─────────┐
        │ PostgreSQL │   │    Redis    │
        │ + pgvector │   │ broker/cache│
        └────────────┘   └───┬─────────┘
                             │
             ┌───────────────┼────────────────┬──────────────┐
             │               │                │              │
      worker-default  worker-telegram   worker-bale     beat (scheduler)
```

`worker-telegram` and `worker-bale` are separate Celery queues **on purpose** — see
R-03 (egress) in the analysis. They may run on different hosts in different regions.

---

## 2. Layering

Strict, one direction only. An arrow means "may import".

```
  api (DRF views, serializers, permissions, routers)
        │
        ▼
  services (use cases, transactions, orchestration)   ◄── tasks (Celery)
        │                                                    ▲
        ▼                                                    │
  domain (entities, value objects, state machines, policies) │
        │                                                    │
        ▼                                                    │
  models (Django ORM, persistence only) ──────────────────────┘
```

Rules (enforced in review and by `importlinter`):

- **Views contain no business logic.** They validate input, call one service, shape output.
- **Serializers contain no business logic.** Field-level validation only.
- **Services own transactions.** `@transaction.atomic` lives here, never in views or models.
- **Models own persistence.** Managers may scope querysets; they never orchestrate.
- **Domain is import-free** of Django where practical (pricing, state machines, money) so it
  is unit-testable without a database.
- **Tasks are thin.** A Celery task resolves arguments and calls a service. No logic.

### Standard app layout

```
apps/<app>/
├── __init__.py
├── apps.py
├── models.py            # or models/ package
├── domain/              # pure logic, no ORM where possible
├── services/            # use cases; the only public entry point for other apps
├── selectors.py         # read-side queries (tenant-scoped)
├── api/
│   ├── serializers.py
│   ├── views.py
│   ├── permissions.py
│   └── urls.py
├── tasks.py
├── events.py            # domain events this app publishes
├── admin.py
├── migrations/
└── tests/
```

**Cross-app rule:** an app may import another app's `services/` and `models` (for FKs), but
never another app's `api/` or internal `domain/` internals.

---

## 3. Applications and ownership

| App | Owns |
|---|---|
| `core` | Base models, `AmountField`, encryption fields, outbox, common errors, pagination, health |
| `accounts` | `User`, authentication, staff RBAC roles |
| `customers` | `Tenant` (the customer org), memberships, Owner/Manager/Staff roles, invitations |
| `businesses` | `BusinessProfile`, working hours, contact, location, branding |
| `business_templates` | `BusinessTemplate`, its feature sets and defaults |
| `features` | `Feature` catalogue, manifests, per-platform/template availability |
| `pricing` | `PriceList`, `PriceVersion`, quote calculation, currency & money rules |
| `orders` | `Quote`, `Order`, `OrderItem`, order state machine |
| `payments` | `PaymentMethod`, `Payment`, `PaymentReceipt`, provider abstraction |
| `bots` | `Bot`, `BotPlatformInstance`, `BotConfiguration`, `BotCredential`, `BotFeature` |
| `provisioning` | Provisioning saga, strategies, bot pool |
| `bot_runtime` | Webhook ingress, update dispatch, session FSM, outbound gateway |
| `platforms` | Adapter registry + `telegram/`, `bale/`, `preview/` adapters |
| `appointments` | Services, staff, slots, bookings, reminders |
| `commerce` | Categories, products, cart, business orders |
| `crm` | Business contacts, leads, notes, tags |
| `notifications` | Event → channel fan-out, templates, delivery log |
| `analytics` | Event ingestion, rollups, dashboards |
| `support` | Tickets, messages, attachments |
| `subscriptions` | Plans, subscriptions, expiry/grace/suspension |
| `ai` | Knowledge base, embeddings, assistant, provider abstraction, budgets |
| `audit` | Audit log writer + query API |
| `i18n_content` | Database-backed translations for dynamic content |

Naming deviations from spec §38 are listed in the analysis, §8.

---

## 4. Channel independence

The core never knows what Telegram is.

```
   Feature handlers  ──emit──►  Reply / Prompt / Menu   (abstract)
                                        │
                            ┌───────────┴────────────┐
                            │   Adapter registry     │
                            └──┬────────┬─────────┬──┘
                               │        │         │
                        Telegram    Bale     Preview
```

### Contracts

```python
# platforms/base.py  (illustrative — implemented in Phase 4)

class Capabilities(NamedTuple):
    inline_keyboards: bool
    reply_keyboards: bool
    max_buttons_per_row: int
    media_groups: bool
    message_editing: bool
    web_app: bool
    max_text_length: int

class InboundEvent:          # normalised, platform-free
    platform: str
    bot_instance_id: UUID
    chat_ref: str
    user_ref: str
    kind: Literal["message", "callback", "command", "contact", "photo", ...]
    text: str | None
    payload: dict
    locale_hint: str | None

class Reply:                 # what a feature returns
    text_key: str            # translation key, never a literal
    params: dict
    choices: list[Choice]
    attachments: list[Attachment]
    expects: Expectation | None

class PlatformAdapter(Protocol):
    slug: str
    capabilities: Capabilities
    def parse(self, raw: dict) -> InboundEvent: ...
    def render(self, reply: Reply, ctx: RenderContext) -> list[OutboundMessage]: ...
    def set_webhook(self, instance, url, secret) -> None: ...
    def get_me(self, credential) -> BotIdentity: ...
```

**Degradation ladder** when a capability is missing:
`inline keyboard → reply keyboard → numbered text menu`; `media group → sequential sends`;
`edit message → send new message`. Chosen by the adapter, never by a feature.

Every adapter must pass `tests/conformance/` — the same scenario suite, recorded fixtures,
no live network.

---

## 5. Feature module contract

A feature is a self-contained package that declares everything about itself:

```python
MANIFEST = FeatureManifest(
    slug="appointment",
    category="appointment",
    requires=["business_profile"],
    platform_requirements=PlatformRequirements(needs_inline_keyboards=False),
    config_schema=AppointmentConfigSchema,     # validated per bot
    menu=[MenuEntry(key="menu.appointment.book", route="appointment:book")],
    handlers={"appointment:book": book_handler, ...},
    price_keys=["feature.appointment.setup", "feature.appointment.monthly"],
    permissions=["appointments.view", "appointments.manage"],
)
```

The builder UI, pricing engine, provisioning and runtime all read this one object. Adding a
feature means adding a package — no engine is modified.

### Where manifests live and how they are found

Each manifest lives in the app that implements it — `apps/appointments/manifest.py`,
`apps/commerce/manifest.py` — and is discovered at app-ready by `features.registry`, which
imports `manifest` from every installed app and indexes by slug.

The registry is code; the `feature` table is data; they must agree. A Django system check
(`features.E001`) fails startup when an active `Feature` row has no manifest, or a manifest
has no row. Without that check the two drift silently and a customer buys a feature the
runtime cannot route — so it is a hard startup failure, not a warning.

---

## 6. Request paths

### 6.1 Customer buys a bot

```
Builder (web │ TG builder bot │ Bale builder bot)
        │  same REST API
        ▼
  pricing.services.build_quote()        → Quote (frozen prices, expires_at)
        ▼
  orders.services.place_order(quote)    → Order[PENDING_PAYMENT]
        ▼
  payments.services.submit_receipt()    → Order[PAYMENT_REVIEW]
        ▼
  admin approve → payments.services.approve()  (emits OrderPaid)
        ▼
  provisioning.tasks.run_saga(order)    → Order[PROVISIONING → … → ACTIVE]
```

### 6.2 An end user talks to a bot

```
POST /webhooks/telegram/{bot_public_id}/
   → authenticate secret (constant time)
   → persist InboundUpdate (raw)
   → enqueue dispatch task          ⟵ view returns 200 here, <50ms
        │
        ▼
  bot_runtime.dispatch
   → resolve bot instance, tenant, config, enabled features
   → adapter.parse() → InboundEvent
   → load Session (Redis, DB-backed)
   → route to feature handler (FSM state or menu route)
   → handler returns Reply
   → adapter.render() → OutboundMessage[]
   → Outbound Gateway (per-bot + per-chat token bucket) → platform API
```

The gateway is the **only** code allowed to call a platform HTTP API.

---

## 7. Multi-tenancy

Shared database, shared schema, tenant foreign key. Enforced in four layers:

1. `TenantOwnedModel` base with a non-null `tenant` FK and a composite index on
   `(tenant_id, <lookup>)`.
2. `TenantQuerySet.for_tenant()`, applied **automatically** by `TenantScopedViewSet` — it is
   in the base class, so it cannot be forgotten.
3. Active tenant **selected** by the `X-Tenant` header and **authorized** against the
   principal's memberships, plus object-level permission checks.
4. Automated cross-tenant test sweeping every registered route, and a structural test that
   every viewset over a `TenantOwnedModel` inherits `TenantScopedViewSet` (see SECURITY.md).

Phase 10 adds PostgreSQL RLS as defence-in-depth.

Bot end-users (a clinic's patients) are **not** platform users. They are
`BusinessContact` rows scoped to the tenant, with no credentials and no login.

---

## 8. Money

- Stored as **integer minor units** + ISO currency code (`AmountField` composite).
- Per-currency exponent table: IRR 0, USD 2, EUR 2, USDT 6.
- **Toman is a display unit of IRR**, not a currency. Conversion (÷10) happens in the
  formatter only.
- No FX conversion inside an order. Each currency has its own admin-maintained price list.
- A single order carries exactly one currency (spec §13).

---

## 9. Events and the outbox

Domain events (`OrderPlaced`, `PaymentApproved`, `BotActivated`, `ProvisioningFailed`,
`AppointmentBooked`, …) are written to an `OutboxMessage` table **inside the same
transaction** as the state change. A relay task publishes them to Celery. Notifications and
analytics are consumers. This makes fan-out replayable and prevents "the order was paid but
the email never went out" inconsistencies.

---

## 10. Configuration over code

Everything customer-specific is data: prices, features, templates, translations, welcome
messages, menus, working hours, payment methods, wallets, branding. There is no per-customer
branch, file, or deployment. A purchase creates rows, never a codebase.

---

## 11. Technology

| Concern | Choice |
|---|---|
| Backend | Python 3.12, Django 5, DRF |
| DB | PostgreSQL 16 + pgvector |
| Cache/broker | Redis 7 |
| Async | Celery 5 + beat |
| Frontend | Next.js (App Router), TypeScript, Tailwind, shadcn/ui |
| Auth | JWT access/refresh (rotating, blacklist) + session for Django admin |
| Storage | S3-compatible, private buckets, signed URLs |
| Container | Docker + docker compose; horizontally scalable services |

---

## 12. Architecture decision records

ADRs live in [docs/adr/](docs/adr/). Every decision above with a trade-off gets one.
Initial set: ADR-0001 modular monolith · ADR-0002 provisioning strategy · ADR-0003 adapter
capabilities · ADR-0004 money representation · ADR-0005 tenancy enforcement ·
ADR-0006 webhook-first runtime.
