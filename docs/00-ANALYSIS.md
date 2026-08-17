# Phase 0 — Specification Analysis, Risks, Assumptions & Proposed Improvements

Status: **Accepted (Phase 0)** · Date: 2026-08-10

This document is the response to spec §66 ("First Implementation Task"). It records what
the specification gets right, what it assumes that is **not true in reality**, and the
decisions taken before any production code is written.

Companion documents: [ARCHITECTURE.md](../ARCHITECTURE.md), [DATABASE.md](../DATABASE.md),
[API.md](../API.md), [PHASES.md](../PHASES.md), [SECURITY.md](../SECURITY.md).

---

## 1. Executive summary

The specification is coherent and the modular-monolith / adapter / configuration-driven
approach is the right one. Four things in it are **factually wrong or unbuildable as
written**, and they must be resolved before Phase 4, because they change the product flow
the customer sees:

| # | Issue | Severity | Resolution |
|---|-------|----------|------------|
| R-01 | "Automated Telegram bot provisioning" does not exist. There is no Bot API method to create a bot. | **Blocker** | Guided Token Handoff + Bot Pool (§3.1) |
| R-02 | Bale is *Telegram-like*, not Telegram-compatible. Adapter cannot be a subclass of the Telegram one. | **High** | Capability-negotiated adapters (§3.2) |
| R-03 | Network egress: Telegram and Bale are generally not reachable from the same jurisdiction. | **High** | Per-platform egress profiles (§3.3) |
| R-04 | "Thousands of bots" + long polling is incompatible with the "no process per bot" rule. | **High** | Webhook-first ingress, sharded fallback poller (§3.4) |

Everything else is engineering risk, addressed in §4–§6.

---

## 2. What the spec gets right (kept unchanged)

- Modular monolith over microservices for v1.
- Channel-independent core with adapters at the edge.
- Configuration-driven bots rather than per-customer codebases.
- Centralised pricing engine with price snapshotting into orders.
- Manual payments first, behind a provider abstraction.
- Explicit order state machine.
- Async provisioning via Celery.
- Strict multi-tenancy enforced at the service layer.
- i18n designed in from the start rather than retrofitted.

---

## 3. Blocking findings and their resolutions

### 3.1 R-01 — Telegram/Bale bots cannot be created programmatically

**Reality.** Bot creation on Telegram happens exclusively through a conversation with
`@BotFather`, which is a *user-facing* bot. The Bot API has no `createBot` method. The only
way to automate it is to drive BotFather from a **user account** over MTProto
(Telethon/Pyrogram). That path is fragile (BotFather's prompts are free text and change),
heavily rate-limited, and puts the driving phone number at real risk of being banned. Bale
has the same shape of restriction and no documented automation surface at all.

The spec's promise — *"The customer must NOT be required to … know bot tokens"* — therefore
cannot be met by pure API automation.

**Decision: a three-track provisioning strategy**, selected per order by admin policy.

1. **Bot Pool (default for "zero-touch" buyers).**
   Operations pre-creates a stock of bots under platform-controlled names
   (`@acme_clinic_01_bot`, …) and stores their tokens encrypted. Provisioning = *assign an
   unused pool entry*, rename its display name/description/commands via
   `setMyName` / `setMyDescription` / `setMyCommands`, point the webhook at us, done.
   Fully automatic, seconds, no customer involvement. Trade-off: the customer does not get
   a vanity `@username` (the `@username` is fixed at BotFather creation time and **cannot**
   be changed via the Bot API). Sold as the "Instant" tier.

2. **Guided Token Handoff (default for "custom username" buyers).**
   The dashboard walks the customer through a ~60-second BotFather flow with copy-paste
   blocks and screenshots, they paste the token **once**, we validate it with `getMe`,
   encrypt it, take ownership of the webhook, and never show it again. The customer keeps
   the vanity username; we keep the operational control the spec wants. Sold as the
   "Custom" tier.

3. **Assisted MTProto automation (internal, feature-flagged, off by default).**
   A supervised operations tool that drives BotFather from a platform-owned account to
   *refill the pool*, never on the customer request path. Isolated behind
   `PROVISIONING_MTPROTO_ENABLED`, rate-limited, with a manual fallback queue. This keeps
   the risk inside operations instead of on the customer's paid order.

The `ProvisioningStrategy` interface makes these interchangeable; the order stores which
one was used.

> **Resolved 2026-08-11.** Both customer-facing tiers were approved: **Instant** (bot pool)
> and **Custom username** (guided token handoff). MTProto remains ops-only and
> flag-gated. See [ADR-0002](adr/0002-provisioning-strategy.md).

### 3.2 R-02 — Bale is not Telegram

Bale exposes a Telegram-Bot-API-*shaped* HTTP API at a different base URL with a
**subset** of methods and differing semantics (inline mode, web apps, some keyboard and
media types, file handling, and update payload fields all differ or are absent). Writing
the Bale adapter as "Telegram adapter with a different base URL" will produce silent
runtime failures in production for exactly the features customers paid for.

**Decision.** Each adapter declares a **capability manifest** (`supports_inline_keyboards`,
`supports_web_app`, `max_buttons_per_row`, `supports_media_group`, `supports_editing`, …).
The core never emits platform widgets; it emits an abstract `Reply` (text + choices +
attachments + metadata). The adapter renders it *within its declared capabilities*, and a
documented **degradation ladder** covers the gaps (inline keyboard → reply keyboard →
numbered text menu). Feature availability per platform is data (`FeaturePlatformAvailability`),
so the pricing/builder UI can refuse to sell a feature on a platform that cannot run it.

Every adapter must pass the same **conformance test suite** against a recorded-fixture
transport. Real API behaviour is verified in a Phase 5 spike before the Bale adapter is
priced as GA.

### 3.3 R-03 — Egress reachability (not mentioned in the spec at all)

Telegram's API is typically unreachable from Iranian infrastructure; Bale is an Iranian
platform and is in practice best (sometimes only) reachable from inside Iran. A single
deployment region cannot serve both reliably.

**Decision.** All outbound platform traffic goes through a per-platform **egress profile**
(`base_url`, `proxy_url`, `timeouts`, `retry policy`, `ca_bundle`), resolved from config,
never hard-coded. The runtime is split into `worker-telegram` and `worker-bale` Celery
queues so the two can be scheduled onto different hosts/regions with different egress
without any code change. Inbound webhooks likewise terminate on a platform-specific
hostname. Health checks probe reachability per platform and surface it on the admin
System Health panel.

### 3.4 R-04 — Polling does not scale; webhooks are mandatory

Long polling requires an open connection per bot. At 1,000 bots that is 1,000 concurrent
loops — a direct violation of spec §58 ("avoid one process per bot").

**Decision.** Webhook-first. One ingress route,
`POST /webhooks/{platform}/{bot_public_id}/`, with a per-bot secret (Telegram
`secret_token` header where supported; HMAC over the raw body plus an unguessable
`bot_public_id` where not). The view does *nothing* but authenticate, persist a raw
`InboundUpdate`, and enqueue — target p99 under 50 ms so the platform never retries us.
A **sharded multiplexed poller** exists only for local development and for bots whose
platform/deployment cannot receive webhooks: N worker processes, each polling a hash-slice
of bots cooperatively, never one process per bot.

---

## 4. Additional risks (non-blocking, mitigated by design)

**Multi-tenancy leakage (highest ongoing risk).** A single forgotten `.filter(tenant=…)`
leaks another business's patient list. Mitigations: `TenantOwnedModel` base class, a
tenant-scoped default manager, a lint rule banning `Model.objects.all()` inside
`apps/*/api/`, and an automated cross-tenant test that walks *every registered router
endpoint* with tenant B's token against tenant A's object IDs and asserts 404. PostgreSQL
Row-Level Security is added as defence-in-depth in Phase 10.

**Money precision.** Floats are banned. Amounts are stored as integer **minor units** plus
a currency code, with a per-currency exponent table (IRR 0, USD 2, USDT 6, BTC 8). *Toman
is not a currency* — it is a presentation unit of IRR (÷10) and is handled in the
formatting layer only. No runtime FX conversion inside an order: each currency has its own
admin-maintained price list, so prices never drift with exchange rates and disputes are
impossible.

**Price snapshotting.** Prices live in immutable `PriceVersion` rows. A `Quote` (with
`expires_at`) is produced by the builder and frozen into `OrderItem`s that copy both the
`price_version_id` *and* the numeric values, so a later version change or a deleted feature
can never rewrite history.

**Receipt fraud and untrusted uploads.** Receipts are attacker-controlled files reaching an
admin's browser. Mitigations: private storage only (never `MEDIA_URL` public), short-TTL
signed URLs, content-sniffed MIME allowlist, image re-encode + EXIF strip, size caps,
`Content-Disposition: attachment`, a strict CSP on the admin, an AV scan hook, and a
**perceptual+SHA-256 hash index** to catch the same receipt submitted against several
orders. Crypto `tx_hash` carries a global unique constraint for the same reason.

**Celery is at-least-once.** Every task must be idempotent by key. Provisioning is modelled
as an explicit saga (`ProvisioningJob` → ordered `ProvisioningStep`s, each with its own
state, attempt counter and idempotency key) rather than a chain of side effects, so a retry
resumes instead of re-running.

**Credential exposure.** Envelope encryption: a per-credential DEK wrapped by a KEK from
env/KMS, with a key-version tag so rotation is possible. Tokens are never fields on any
serializer; a security test scans every API response body for token-shaped strings.

**Cross-channel identity linking (§47) is an account-takeover vector.** Linking a Telegram
account to a platform account must use a short-lived, single-use, session-bound nonce
delivered as a deep link (`/start <nonce>`), never a match on phone or email.

**Dynamic-content i18n.** `gettext` covers static UI strings, but templates, features and
per-bot messages are database rows. Those use side-table translations
(`<Model>Translation(locale, field…)`) with a resolution chain
*bot override → template default → platform default → source locale*.

**Persian calendar & time.** All instants are stored UTC; Jalali is a rendering concern.
Appointments additionally store the business timezone used at booking time so DST/tz
changes cannot silently move a booked slot.

**Platform rate limits.** Telegram enforces ~30 messages/second globally and ~1/second per
chat; reminder blasts will hit this. All outbound traffic goes through a single
**Outbound Gateway** with a Redis token bucket per bot and per chat, plus a retry queue
honouring `retry_after`. Features never call the platform API directly.

**Subscription suspension must actually bite.** On `SUSPENDED`, the runtime rejects updates
and the webhook is removed — otherwise expiry is cosmetic and the service is free.

**AI cost runaway.** Per-tenant token budgets, hard monthly caps, cached embeddings, and a
provider abstraction so model choice is admin configuration. Knowledge base uses `pgvector`
in the same PostgreSQL instance (no extra infrastructure in v1).

---

## 5. Assumptions (to be confirmed)

1. Bot tokens obtained via Guided Token Handoff may be stored and used by the platform on
   the customer's behalf — covered by the Terms of Service (legal review required).
2. Manual payment review is acceptable operationally at launch volume; no gateway in v1.
3. The platform can deploy compute in at least two egress contexts (see R-03), or accept
   proxying for one of the two platforms.
4. Iranian customers pay in IRR/Toman by card transfer; international customers pay in
   USD/EUR-denominated crypto. Currencies are not converted between each other.
5. A "customer" (tenant) may own multiple bots; a bot belongs to exactly one tenant.
6. Recurring billing is *tracked* automatically but *charged* manually in v1 (spec §50).
7. Bale's webhook support and per-method behaviour will be verified by spike before the
   Phase 5 estimate is committed.
8. Business end-users (a clinic's patients) are **not** platform accounts — they are
   tenant-scoped `BusinessContact` records with no login.

---

## 6. Proposed improvements beyond the spec

1. **Feature Manifest contract.** Each feature module ships a declarative manifest (slug,
   menu entries, handlers, required config schema, permissions, platform requirements,
   dependencies, price keys). The builder UI, pricing engine, provisioning and runtime all
   read the same manifest, so adding a feature touches one package and zero engines.
2. **Quote as a first-class object**, separate from `Order` — makes the builder resumable
   across website/Telegram/Bale (§18) without creating junk orders.
3. **Transactional outbox + domain events.** `OrderPaid`, `BotActivated`, `AppointmentBooked`
   are published to an outbox table in the same transaction and consumed by notifications
   and analytics. Removes fan-out coupling and makes both replayable.
4. **Platform-agnostic conversation FSM** with Redis-backed session state and DB durability,
   so a multi-step booking survives a worker restart and behaves identically on both channels.
5. **`PreviewAdapter`** — the §48 pre-payment preview implemented as a third adapter over the
   same core. It renders to JSON for the web preview *and* doubles as the test double,
   which continuously proves the channel-independence claim is real.
6. **Conformance test suite** run against every adapter (§3.2).
7. **Sandbox tenant** with seeded demo data for sales demos and E2E tests.
8. **PostgreSQL RLS** as defence-in-depth for tenancy (Phase 10).
9. **Webhook secret rotation** with an overlap window (accept old+new during rotation).
10. **`AmountField`** (integer minor units + currency) as a reusable composite, so no
    developer ever chooses a float or forgets the currency.

---

## 7. External integrations & their technical limits

| Integration | Used for | Hard limit / caveat |
|---|---|---|
| Telegram Bot API | Runtime, provisioning | No bot creation; 30 msg/s global, 1 msg/s per chat; 20 MB download / 50 MB upload; webhook needs public HTTPS on 443/80/88/8443 with a valid cert |
| Telegram MTProto (optional) | Pool refill only | ToS-sensitive, ban risk, unstable prompts — ops-only, flagged off |
| Bale Bot API | Runtime, provisioning | Subset of Telegram API; capabilities to be verified by spike; egress constraints |
| PostgreSQL 16 + pgvector | Primary store, AI KB | Single instance in v1; read replicas deferred |
| Redis 7 | Broker, cache, sessions, rate-limit buckets | Not a durable store — never the only copy of anything |
| S3-compatible object storage | Receipts, logos, documents | Private buckets only, signed URLs |
| SMTP | Email notifications | Deliverability/SPF-DKIM is an ops task |
| LLM provider (Anthropic default) | AI module | Cost caps per tenant; provider abstracted |

---

## 8. Deviations from the spec's suggested app list

| Spec name | Implemented as | Why |
|---|---|---|
| `templates` | `business_templates` | `templates` collides with Django's `TEMPLATES` setting and template directories; a real source of confusion |
| `platforms` | `platforms` + `platforms/{telegram,bale,preview}` | Keeps the spec name, adds the adapter sub-packages |
| — | `pricing` (new) | The pricing engine is a distinct domain from `features`; it must not be owned by the feature catalogue |
| — | `provisioning` (new) | The provisioning saga is separate from bot representation in `bots` |
| — | `i18n_content` (new) | Database-backed translations for dynamic content (§4) |

All other app names follow spec §38 exactly.
