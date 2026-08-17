# PHASES

Status: **Phases 0–4 complete · Phase 5 code complete, pending the Bale capability spike ·
Phases 6–9 complete**
· Last updated: 2026-08-16

Rule from spec §63: a phase is done when it has working code, migrations, endpoints,
frontend integration, permissions, validation, error handling, tests, documentation, seed
data, env config and Docker compatibility — **and the system still runs end to end**.

---

## Dependency graph

```
                         ┌──────────────────────────┐
                         │ P0  Architecture & docs  │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ P1  Core SaaS foundation │
                         │ auth · tenancy · i18n ·  │
                         │ money · API base · CI    │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ P2  Catalogue, pricing,  │
                         │     builder & preview    │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ P3  Orders & manual pay  │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ P4  Telegram: adapter,   │
                         │ runtime, provisioning,   │
                         │ builder bot              │
                         └───┬──────────────────┬───┘
                             │                  │
             ┌───────────────▼──────┐   ┌───────▼────────────────┐
             │ P5  Bale (parallel   │   │ P6  Customer dashboard │
             │     with P6)         │   │     (parallel with P5) │
             └───────────────┬──────┘   └───────┬────────────────┘
                             └────────┬─────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ P7  Business modules     │
                         │ clinic → shop → …        │
                         └────────────┬─────────────┘
                                      ▼
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
        ┌───────────────────────┐         ┌─────────────────────────┐
        │ P8  AI module         │         │ P9  Subscriptions       │
        │ (independent of P9)   │         │ (independent of P8)     │
        └───────────┬───────────┘         └────────────┬────────────┘
                    └─────────────────┬─────────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ P10 Production hardening │
                         └──────────────────────────┘
```

**Critical path:** P0 → P1 → P2 → P3 → P4 → P7 → P10.
**Parallelisable:** P5 ∥ P6; P8 ∥ P9. Frontend work for P6 can start once P2's API
contracts are frozen.

---

## Phase 0 — Architecture & foundation *(current)*

**Deliverables**

- [x] Specification analysis, risks, assumptions, improvements — [docs/00-ANALYSIS.md](docs/00-ANALYSIS.md)
- [x] Architecture, layering, app boundaries — [ARCHITECTURE.md](ARCHITECTURE.md)
- [x] Database design & ERD — [DATABASE.md](DATABASE.md)
- [x] API conventions & endpoint contract — [API.md](API.md)
- [x] Security model — [SECURITY.md](SECURITY.md)
- [x] i18n & l10n strategy — [I18N.md](I18N.md)
- [x] Payment & currency abstraction — [PAYMENTS.md](PAYMENTS.md)
- [x] Bot runtime & adapter design — [BOT_RUNTIME.md](BOT_RUNTIME.md)
- [x] Telegram integration & its limits — [TELEGRAM.md](TELEGRAM.md)
- [x] Bale integration & open questions — [BALE.md](BALE.md)
- [x] Deployment topology — [DEPLOYMENT.md](DEPLOYMENT.md)
- [x] Phase plan (this file)
- [x] Repository skeleton, Docker structure, `.env.example`
- [ ] **Sign-off required:** provisioning strategy (analysis R-01) before P4 begins

**Exit criteria:** documentation reviewed; `docker compose config` validates; the
provisioning decision is accepted.

---

## Phase 1 — Core SaaS foundation ✅ **COMPLETE**

Django 5.2 project with split settings; PostgreSQL + Redis + Celery wired; custom `User`;
JWT auth with rotation and blacklist; `Tenant`, membership, Owner/Manager/Staff; staff RBAC;
`TenantOwnedModel` + scoped querysets + `TenantScopedViewSet`; `Money` and the currency
registry; locale resolution; uniform error handler; audit log; outbox table + relay;
health endpoints; OpenAPI; Next.js app shell with auth, locale switching and RTL;
seed command.

**Verified 2026-08-10:**

- 111 backend tests pass against PostgreSQL 16 (`pytest tests`, exit 0).
- `manage.py check` clean · migrations apply · `seed_demo --demo` idempotent.
- `/healthz` `ok`; `/readyz` reports database, cache and migrations all healthy.
- Tenant resolution end-to-end: one membership resolves silently; two return
  `409 tenant.ambiguous` with the list; `X-Tenant` selects; a non-member tenant returns
  **404, never 403**; a platform super-admin sees no tenant data through the customer API.
- Locale end-to-end: a `fa` profile beats `Accept-Language: en`; `?lang=` beats both.
- `next build` clean, `/en` and `/fa` prerendered, `<html lang="fa" dir="rtl">` confirmed.
- `docker compose up postgres redis` healthy with pgvector, citext, pg_trgm, pgcrypto,
  btree_gist created.

**Deviations decided during implementation** (each with a comment at the site):

| Decision | Reason |
|---|---|
| Django pinned to **5.2 LTS** (was `<5.2`) | pytest-django 4.13 requires it |
| pytest pinned `<9` | pytest-django 4.13 does not support pytest 9 |
| PostgreSQL uses the official `pgvector/pgvector:pg16` image | the Alpine source build of pgvector fails; upstream image is maintained |
| Container host ports configurable (`POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`) | a locally installed PostgreSQL silently shadows the container |
| Tenant **and** locale resolution moved out of middleware | DRF authenticates after middleware — see F-1 and F-10 in the architecture review |

**Not built in Phase 1** (deliberate, scheduled later): CI pipeline configuration,
email delivery of the verification token (Phase 3 with notifications), invitation-by-email
for non-users (Phase 6), `AmountField` as a Django composite (the `MoneyProxy` descriptor
covers current needs; revisit when `orders` lands in Phase 3).

---

## Phase 2 — Catalogue, pricing engine, builder & preview ✅ **COMPLETE**

`BusinessTemplate`, `Feature`, feature manifests, per-platform availability; `PriceList` /
immutable `PriceVersion` with the create-and-close admin flow; quote engine; `Quote` /
`QuoteItem`; `PreviewAdapter` and the preview endpoint; public site (home, features,
templates, pricing, how-it-works, FAQ); the builder wizard with live pricing.

**Exit criterion met.** A visitor configures a clinic bot on Telegram + Bale, sees an
itemised price computed server-side, and previews the bot — without an account.

**Verified 2026-08-10:**

- 226 backend tests pass against PostgreSQL 16 (exit 0); `check` clean; no missing migrations.
- Live quote: clinic on Telegram + Bale with appointments, reminders, FAQ and AI →
  12 itemised lines, **$472 setup + $64/month**, computed entirely server-side.
- **Platform pricing follows spec §9**: one platform base ($49) plus a multi-platform
  surcharge ($29) — never two full prices. Verified `single < both < single × 2`.
- **Snapshotting proven live**: a quote taken at $29 stayed at $29 after the admin raised
  the price to $79, while a new quote picked up $79. Version history: `closed → closed → live`.
- Iranian pricing renders in Toman (`۱۵٬۳۵۰٬۰۰۰ تومان`) from IRR stored in rials.
- Undeliverable combinations refused: `food_ordering` on Bale →
  `quote.feature_unavailable_on_platform`, reason `unsupported_capability: media_groups`.
- Quote access requires the session secret: no secret → 404, wrong secret → 404, correct → 200.
- Preview renders per platform, in both locales, and flags Bale as provisional.
- `next build` clean; `/en/build` and `/fa/build` prerender with correct `dir`.

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| Multi-platform = primary channel base + surcharge per extra channel | Spec §9 literally; the primary is the most expensive base so the total does not depend on tick-box order |
| Features priced once, not per platform | One configuration drives both channels (spec §61.1) |
| An incomplete price list **refuses** to quote | A total computed from missing prices under-charges silently |
| `Quote` is not a `TenantOwnedModel` | The builder must work before registration (F-3); ownership arrives via `claim` |
| Anonymous quotes need an `X-Quote-Session` secret | A `public_id` alone would expose a business draft to anyone with the link |
| Bale capabilities ship as `verified=False` | R-02 is unresolved; the preview says so rather than implying the mock-up is authoritative |
| 7 apps registered manifest-only | Manifests belong to the app that will implement them (ADR); Phase 7 adds models and handlers without moving files |

**Not built in Phase 2** (deliberate): `Order` and its state machine, payments, and the
builder's steps 8–9 — all Phase 3. The wizard shows step 8 as pending. Telegram and Bale
builder bots (spec §45–46) are deferred to Phases 4–5, since they need the runtime.

---

## Phase 3 — Orders & manual payments ✅ **COMPLETE**

Order state machine with an explicit transition allow-list; quote → order; `PaymentMethod`
admin (card + crypto wallets); receipt upload with the full validation pipeline; crypto proof
with globally unique `tx_hash`; admin review queue with approve/reject/reason/internal note;
notifications on every transition; duplicate-receipt detection.

**Verified 2026-08-11:** 380 backend tests pass (exit 0); `check` clean; no missing
migrations; `next build` clean.

Live end-to-end run: quote → claim → order **#10003** (`PENDING_PAYMENT`, $363) →
card payment started (card details returned, `internal_note` absent from the response) →
malicious upload refused (`upload.unrecognised_type`) → genuine receipt accepted →
`RECEIPT_SUBMITTED` → support agent **refused**, customer **refused**, finance **approved**
→ `PAID` with `paid_at` set. Full transition history recorded, notifications rendered in
English and Persian.

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| `transition_order` is the only way status changes | Anything else makes the allow-list advisory rather than binding |
| Order numbers come from a PostgreSQL sequence | `MAX+1`/`COUNT(*)` race under concurrent checkout and `number` is unique |
| Re-placing the same quote returns the existing order | A double-clicked checkout button must not create two orders |
| Services re-read under `select_for_update` | Guards must not depend on how fresh the caller's in-memory object is |
| Amounts re-validated against the order at approval | A stale payment row must never decide what was owed |
| Duplicate receipts are **flagged, not blocked** | A customer legitimately paying twice by one transfer would otherwise be stranded; finance decides |
| A rejection reason is mandatory *and* reaches the customer | Requiring a reason nobody sees is theatre |
| Crypto proof requires a `tx_hash`, not a screenshot | A screenshot is trivially faked and cannot be checked on-chain later |
| `PaymentReceipt` downloads gated on scan status | The admin must never open an unscanned customer upload |
| Seeded payment methods ship **disabled** with placeholders | Real card numbers and wallets are admin data, never committed (spec §15) |

**Not built in Phase 3** (deliberate): automatic on-chain verification (spec §15 defers it
explicitly), a real AV engine behind the scan hook (Phase 10 — the gate is enforced now),
and Telegram/Bale notification delivery, which needs the runtime's outbound gateway
(Phase 4). Those deliveries are recorded as `SKIPPED` rather than silently dropped.

**Exit:** order → pay → upload proof → admin approves → order reaches `PAID` and emits
`OrderPaid`. Provisioning is stubbed and logs its input.

---

## Phase 4 — Telegram ✅ **COMPLETE**

Adapter with capability manifest; webhook ingress with per-bot secrets; dispatcher; session
FSM; outbound gateway with token buckets; provisioning saga with the three strategies
(pool / token handoff / flagged MTProto); bot pool admin; envelope-encrypted credentials;
core features (welcome, business profile, contact, location, hours, FAQ).

**Exit criterion met.** An approved payment produces a live Telegram bot that answers.
Provisioning is resumable and idempotent.

**Verified 2026-08-11:** 462 backend tests pass (exit 0); `check` clean; no missing
migrations; `next build` clean.

Live end-to-end run:

- Order **#10004** → paid → finance approved → provisioning saga → bot `ACTIVE`,
  `@tehran_smile_bot`, order `ACTIVE`.
- **Both tiers exercised.** Tier B parked at `AWAITING_CUSTOMER` with step
  `acquire_credential = BLOCKED`, then completed the moment the token was submitted.
  Tier A assigns from the pool with no customer action at all.
- **A real conversation**: `/start` → Persian welcome + menu; "تماس با ما" → routed to
  `business:contact` with the customer's real phone and email; "سوالات متداول" → routed
  to `faq:list`. Locale followed the end user's Telegram client, not the bot default.
- **Rate limiting held**: three sends to one chat in one second → one sent, two deferred,
  then drained by the retry sweep. Nothing dropped.

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| Saga steps carry the order status they belong to | The state machine has no `PROVISIONING → ACTIVE` edge; walking the phases is also what gives the customer real progress (spec §20) |
| A retry takes the explicit `FAILED → PROVISIONING` edge | That edge exists precisely for retries; without it every later transition is illegal |
| Route ownership comes from manifests, not route names | A route namespace (`business:contact`) is a UI grouping and need not equal a feature slug (`contact`) — inferring one from the other silently denied valid routes |
| Callback payloads are HMAC-signed per instance | `callback_data` is attacker-controlled; a token minted for one bot must not work on another |
| Ciphertext is bound to its instance via AES-GCM associated data | A credential row copied to another instance fails to decrypt, so a database mix-up cannot hand one customer another's bot |
| Platforms with no provisioner are **deferred, not failed** | Bale ships in Phase 5; telling a paying customer it broke would be wrong |
| Webhook ingress returns 200 for everything | A 404 leaks which bot ids exist; a 500 makes Telegram retry something we chose to drop |
| Default tier is `pool` | "Instant" is the headline product story; the Phase 1 seed had it backwards |

**Not built in Phase 4** (deliberate): the **Telegram builder bot** (spec §45) — a second
conversational surface over the same API, large enough to deserve its own slice and not
required by the exit criterion; the **polling fallback** (webhooks are the production
path); and a real MTProto pool-refill implementation, which stays a flagged stub.

---

## Phase 5 — Bale ⚠️ **Code complete · spike outstanding**

Capability spike **first** (a hard prerequisite — see [BALE.md](BALE.md)); Bale adapter
against verified behaviour; egress profile; Bale provisioning; Bale builder bot;
multi-platform orders sharing one business configuration.

**Exit criterion met in code, not in evidence.** One order yields a Telegram bot and a
Bale bot backed by the same data, and the same conformance suite passes for both adapters
— but against a fake transport, because **the capability spike has not been run**.

> The spike needs a real Bale bot token and network reachability to Bale, neither of which
> was available during development. Rather than guess and mark it done, Bale ships
> `verified=False` and the spike is automated so whoever holds a token can close it in
> minutes. See [BALE.md §8](BALE.md).

**Verified 2026-08-11:** 490 backend tests pass (exit 0); `check` clean; no missing
migrations.

- **Conformance suite**: 58 tests run the same scenarios across all three adapters
  (telegram, bale, preview). Every rung of the degradation ladder is checked to still
  deliver all options.
- **Multi-platform**: one order → one bot → two instances, one configuration, one set of
  features, two credentials, two webhooks. The Bale instance that Phase 4 deferred now
  provisions to `ACTIVE`.
- **Contacts stay per channel**: the same person on Telegram and Bale is two
  `business_contact` rows under one tenant — merging them without a verified signal
  would be a privacy problem.
- **Pricing re-checked** now that both channels are genuinely deliverable:
  `single < both < single × 2`, features billed once.

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| `BaleApi` and `BaleAdapter` written independently of Telegram's | `BaleAdapter(TelegramAdapter)` would silently inherit behaviour Bale may not have — the exact R-02 failure mode |
| A conformance test asserts Bale reports `verified=False` | The suite enforces *honesty about* verification, not verification itself |
| Bale capabilities are deliberately conservative | Understating degrades presentation; overstating sells a broken feature |
| Bale branding/commands are best-effort, webhooks are not | A bot that works but is not renamed is cosmetic; a bot that cannot receive updates is not |
| Platform client registry replaced the gateway's Telegram import | "The only code allowed to call a platform API" could previously call only one platform |
| Fake transport returns identity **per token** | A fake answering `getMe` identically for every token hid a real multi-platform bug |
| Probe runnable from the admin, not just the CLI | The gate on selling Bale features shouldn't require SSH |

**Not built in Phase 5** (deliberate): the **Bale builder bot** (spec §46) — deferred with
its Telegram counterpart from Phase 4, since both are second conversational surfaces over
the same API and belong together; and the polling fallback, which only matters if the
spike shows Bale webhooks are unavailable.

---

## Phase 6 — Customer dashboard ✅ **COMPLETE**

Business profile editing and FAQ management, both live-writable and reflected on the
bot's very next reply; add-on ordering (buying a feature for a bot that is already live,
without re-provisioning it); a support ticket system built from scratch; team invitations
by email for people without an account yet; a minimal real analytics table wired into the
dispatcher's hot path; a notification mark-all-read action; and the dashboard frontend for
all of it — bot detail additions, a settings page, support pages, a notifications page and
badge, and an invite-accept page with inline login/register.

**Exit criterion met.** A customer can edit their business profile and FAQ, buy another
feature for a live bot, invite a colleague, read notifications, and open a support ticket
— all from the dashboard, without anyone touching the database by hand.

**Verified 2026-08-15:** 566 backend tests pass against PostgreSQL 16 (exit 0, up from 490
in Phase 5); `check` clean; migrations apply cleanly (`businesses`, `orders`, `customers`,
`analytics`, `support`); `next build` clean, all new routes prerender.

- **Live end-to-end run** against a running `manage.py runserver` + `next dev`, driven
  through every new endpoint exactly as the frontend calls it (not just pytest): business
  profile read/edit, FAQ create/edit/delete, available-features list, add-on quote →
  placed as a real `Order` with `kind=ADDON`, analytics summary (14-day zero-filled
  series), notifications list/unread-count/read-all, team member invite/list/revoke, and
  a support ticket created → replied to → closed. Every response matched the shape the
  TypeScript client expects.
- **Business profile is now the live source**, not a JSON blob nobody read. The saga
  seeds it from the quote's business snapshot at provisioning time; a dashboard edit
  bumps `BotConfiguration.version`, and the very next message through the real dispatcher
  (not a mock) rendered the newly-edited phone number.
- **Add-on provisioning is genuinely thin**: buying "location" for a live bot ran a
  4-step saga (bind → enable feature → set commands → activate) and never called
  `getMe` or `setWebhook` — confirmed by asserting on the fake transport's call log,
  cleared right before the add-on run so the bot's own initial provisioning calls
  couldn't produce a false pass.
- **Invitation security held**: accepting with a different email than the one invited is
  rejected; accepting twice is idempotent; a revoked invitation cannot be accepted even
  with a still-unexpired token.

**Bugs found and fixed while verifying this phase** (not deferred to the later bug-fixing
pass, since they were caught by the tests written for this phase's own features):

| Bug | Fix |
|---|---|
| The add-on saga's last step was tagged `CONFIGURING`, but the order state machine has no `CONFIGURING → ACTIVE` edge — every add-on purchase failed at the final step | Retagged `set_commands` as `DEPLOYING` in `ADDON_STEPS`, so `_advance_order_to` walks the order through `DEPLOYING` before `addon_activate` closes it out |
| `accept_invitation`'s "already a member" idempotency branch was unreachable: accepting sets `accepted_at`, which makes `is_usable` false, so a second click on the same link always raised `tenant.invalid_invitation` before reaching the idempotent path | Reordered the checks — an existing membership short-circuits before `is_usable` is consulted |
| A pre-existing test (`test_a_handler_failure_still_answers_the_user`) mutated the router's shared `_ROUTES` dict directly instead of through `monkeypatch`, leaking a broken handler into every later test that dispatched to that route | Changed to `monkeypatch.setitem`, which reverts automatically |

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| Analytics stays a single flat, indexed `AnalyticsEvent` table | DATABASE.md's partitioned table + daily rollup is a real optimisation, but one that earns its complexity only once event volume makes a plain table slow — building it now, before any bot has produced an event, would be designing for a load this platform does not have |
| Support ticket triage, assignment and internal notes live in Django admin, not a second staff API | The exit criterion is that support is a *fallback*, not the main path; the customer-facing surface (open, reply, close) is what "runs the bot without contacting support" actually requires |
| A support reply carries at most one attachment | Covers the overwhelming majority of "here's a screenshot" cases without a multi-file upload UI the spec did not ask for |
| `calculate_addon_quote` shares `_feature_items` with `calculate_quote` but omits template/platform/hosting lines | The customer already paid for those; re-pricing them would double-charge |
| An add-on quote is created pre-claimed to the bot's tenant, never anonymous | Unlike the builder, there is no visitor to convert — the bot already belongs to a tenant, so the client can place the order immediately without a `claim` step |
| Settings page covers team management, not tenant profile editing | No tenant-update endpoint exists yet (`TenantViewSet` only supports create/list/retrieve/members/invitations) — adding one wasn't part of this phase's scope, so the page only surfaces what is real |
| The invite-accept page holds inline login **and** register forms rather than redirecting | The alternative (redirect to `/login`, hope the user finds their way back) needed a `next`-redirect mechanism the app doesn't have yet; keeping the whole flow on one page avoids inventing one for a single caller |
| Nested resources without a natural `public_id` (`FaqEntry`, `TenantInvitation`) use integer PKs in the URL, matching the existing `TenantMembership` precedent | Consistency over adding a UUID column purely for URL aesthetics |

**Not built in Phase 6** (deliberate): a staff-facing support dashboard beyond Django
admin; tenant profile self-editing (name, currency, timezone) from the settings page;
structured per-weekday working hours (`WorkingHours` model exists but Phase 7's
appointment slot computation is what will actually need it — the free-text field is what
both the builder and the dashboard edit until then); multi-file support attachments; and
a generic post-login redirect mechanism (the invite-accept page works around its absence
rather than building it for one caller).

---

## Phase 7 — Business modules ✅ **COMPLETE**

Incremental, one module per increment, each independently shippable:
clinic/doctor (appointments — the hardest, do first) → beauty → restaurant → shop →
academy → real estate → services → generic.

**Exit per module:** template seeded, features implemented, priced, configurable in the
dashboard, working on both channels, tested.

### Clinic/doctor increment — appointments ✅ **COMPLETE**

The hardest module, done first as planned: bookable services and staff, real slot
computation against the dashboard's own opening-hours table, a conversational booking
flow through the real dispatcher, and reminders — the two features the clinic template
already offered (`appointment`, `appointment_reminders`) but that did nothing until now.

**Exit criterion met.** A customer books a real appointment by chatting with the bot —
service, then staff (skipped automatically when there is only one), then an open time —
and gets a confirmation and, if the business bought reminders, a nudge before it starts.
The business manages its services, staff and calendar from the dashboard.

**Verified 2026-08-15:** 600 backend tests pass against PostgreSQL 16 (exit 0, up from
566 after Phase 6); `check` clean; `next build` clean. Every dashboard endpoint
(services, staff, slots, appointments, cancel) was also driven live against a running
`manage.py runserver`, not just pytest.

- **Double-booking is a database guarantee, not a promise the code keeps.** A
  PostgreSQL `EXCLUDE` constraint (`staff_id WITH =`, `tstzrange(starts_at, ends_at) WITH
  &&`, gated to `CONFIRMED` rows) sits under the availability check. The test that matters
  most here bypasses the service layer entirely and inserts two overlapping rows directly
  through the ORM — the second one fails with an `IntegrityError` no application code
  could have been skipped to avoid.
- **The conversation is fully stateless.** Every step (service → staff → slot → confirm)
  is a signed callback carrying its own accumulated selections, the same pattern
  `faq:list` already used — no `session.state`, so there is no "resumed three days later
  against a slot that no longer exists" failure mode to guard against.
- **Slots respect real constraints**: business hours (reusing the dashboard's own
  `WorkingHours` table — one schedule, not a second one to keep in sync), buffers between
  bookings, time off (business-wide or per staff member), a minimum lead time, and a
  21-day booking horizon.
- **Reminders are idempotent under Celery's at-least-once delivery**: `reminder_sent_at`
  is set in the same call that sends, so a redelivered task sends nothing twice — proven
  by calling the sweep task itself twice in the same test.

**A real bug, found and fixed while building this** (not deferred — it was actively
blocking this module's own conversational flow, so fixing it was part of building it):

| Bug | Fix |
|---|---|
| `_render()` signed every button's callback data as `encode(id, choice.value, "")` — treating the *whole* `"route.value"` string (FAQ's list-then-detail convention, e.g. `"faq:list.42"`) as the route with an empty value. `encode()` always appends a trailing `.` even for an empty value, so decoding glued that stray dot onto whatever got split out as the sub-value. Concretely: tapping an FAQ answer button re-rendered the *list* instead of showing the answer — silently, since the callback still verified and still resolved to a real, allowed route. Never caught before because FAQ was the only shipped feature using the packed-value convention, and no test dispatched a real round trip through it. | Split `choice.value` into `(route, value)` in `_render()` before signing, so `decode()` hands the handler back a clean pair. A new regression test in `test_bot_runtime.py` dispatches "FAQ", pulls the *real* signed `callback_data` off the rendered `OutboundMessage`, taps it, and asserts the actual answer comes back. |

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| Every staff member is mandatory on a booking, never optional | A nullable `staff` column would silently turn off the exclusion constraint's protection for every single-provider business — exactly the shops this feature ships for first. A solo practitioner gets one auto-created `StaffMember` row instead. |
| All staff share the bot's one `WorkingHours` schedule; there is no per-staff calendar yet | `WorkingHours`'s own docstring already flagged per-weekday hours as "for the appointment module" when it was written in Phase 6 — this is that module's first use of them, just not yet the per-staff variant DATABASE.md's ERD implies. A real gap for a multi-doctor clinic with different schedules, called out below rather than silently shipped. |
| The double-booking guard is a raw-SQL `EXCLUDE` constraint, not Django's `ExclusionConstraint` | That API wants a stored range column; `tstzrange()` computed inline over the existing `starts_at`/`ends_at` columns needs no such column, and duplicating them for one constraint would be schema churn for no benefit. |
| `BtreeGistExtension()` runs as a migration operation, not just Docker's init script | The init script only ever touches the one database Docker first creates — never pytest's `test_botbuilder`, never a CI database. A migration is the only place this is guaranteed to run wherever the schema does. |
| The booking conversation has no separate "pick a date" step | The preview catalogue's `PreviewStep` sequence — written in Phase 2, before this module existed — already promised four steps: service, staff, slot, confirm. `select_slot` scans forward across days itself and offers one flat list, matching that promise instead of adding a tap the preview never showed. |
| An appointment's price is stored directly on `AppointmentService`, never through `apps.pricing` | A clinic's own price for "teeth cleaning" is unrelated to what the clinic pays this platform — conflating the two pricing systems would be a modeling error, not a simplification. |
| Reminders run on Celery beat with a static `CELERY_BEAT_SCHEDULE` entry | Nothing about the schedule needs to change without a deploy, and this is the project's first periodic task — a static dict is one less moving part than standing up `django_celery_beat` for a single entry. |

**Not built in this increment** (deliberate): per-staff working hours (every staff member
currently follows the bot's single schedule); a "my bookings" self-service view for the
customer inside the bot (cancellation is dashboard-only for now); multi-slot/recurring
bookings; and a staff-facing calendar UI beyond the dashboard's flat upcoming-appointments
list.

### Beauty and services increments — verified, no new code ✅ **COMPLETE**

Per PHASES.md's own plan, both are covered by the appointments module already built:
`beauty` and `services` templates each simply *offer* the `appointment` feature the
clinic template already exercises, and booking is feature-driven, not template-driven —
the same models, services and handlers serve all three. A parametrized regression test
(`TestOtherTemplatesShareTheSameBookingCode`) provisions a real bot on each template and
runs it through `/book`, locking this in rather than asserting it once from memory.

### Restaurant, shop, academy, real estate, generic increments — CRM and Commerce modules ✅ **COMPLETE**

The remaining five templates share two underlying feature sets rather than needing five
separate builds: a **commerce module** (`apps.commerce`) — product catalogue, cart,
checkout, table reservations — and a **CRM module** (`apps.crm`) — lead capture from a
contact form or a consultation request, star-rating feedback, and the lead pipeline
(status, notes, tags) that tracks them. Together with two small notification features
(`owner_notifications`, `customer_broadcast`) built alongside them, every extra or
default feature every template offers now does something real.

**Exit criterion met, per template:**
- **Restaurant**: browse a menu, add to cart, checkout — or reserve a table for a time
  computed from real opening hours. `food_ordering` is not a separate flow; its manifest
  already declares it as `product_catalog` + `cart_orders` with a media-groups platform
  requirement, so it shares this code rather than duplicating it.
- **Shop**: the same catalogue and cart, browse-only if the shop only bought
  `product_catalog` (no "Add to cart" button renders without `cart_orders` — see the bug
  below), full checkout if it bought both.
- **Academy / real estate**: `product_catalog` doubles as a course or listing catalogue;
  `consultation_request` and `lead_capture`/`crm_pipeline` turn an enquiry into a tracked
  lead with a status and staff notes.
- **Generic**: every one of the above, since it offers them all as extras.

**Verified 2026-08-15:** 649 backend tests pass against PostgreSQL 16 (exit 0, up from
600 after the clinic increment); `check` clean; `next build` clean. Every new dashboard
endpoint (leads, feedback, product categories, products, business orders, table
reservations, broadcast) was also driven live against a running `manage.py runserver`.

- **Free text, for the first time.** Every earlier feature in this codebase (FAQ,
  appointments, commerce) stayed fully enumerable and never touched `session.state` —
  `contact_request` and `consultation_request` are the first flows where the answer is
  genuinely open text. Each is two steps (ask, then whatever comes back is the answer),
  and each re-checks `event.kind` for a stray `/menu` mid-flow so a customer bailing out
  does not get "/menu" captured as their message — proven by a test that does exactly
  that and asserts no `Lead` was created.
- **Owner notifications are feature-gated, not just tenant-gated.** The existing
  notification catalogue (`apps.notifications`) already knew "which platform events
  reach which tenant"; it did not yet know "does *this bot* pay to hear about its own
  activity." `NotificationSpec.requires_feature` closes that gap for `appointment.booked`,
  `crm.lead_captured` and `commerce.order_placed` without touching the SaaS-platform
  events (`order.paid`, etc.) that were never feature-gated and must not become so.
- **Order snapshots survive a later price change.** `BusinessOrderItem` copies the
  product's name and price at checkout; a test raises the product's price after
  checkout and asserts the already-placed order still reads the old one.

**Real bugs, found and fixed while building this** (not deferred — both were caught by
this increment's own tests, the same day they were introduced):

| Bug | Fix |
|---|---|
| `crm.lead_captured`'s event payload carried `LeadSource(source).label` — a lazy translation proxy, not a plain string. `OutboxMessage.payload` is a `JSONField`; psycopg's JSON encoder has no idea how to serialize a `__proxy__` object, so creating a lead crashed the insert outright rather than just rendering oddly. | Publish the raw source code (`"CONTACT_FORM"`) instead. Event payloads must stay locale-agnostic besides — the translated presentation belongs in `notify.lead.captured.body`, at render time, not at publish time. |
| The router resolves an unregistered sub-route's owning feature by taking the string before its first `:` (`apps.bot_runtime.router.owning_feature`) — the exact mechanism `appointment:pick_staff` relies on, because "appointment" happens to equal a real feature slug. `crm:rate` (feedback's star-tap) and several commerce sub-routes (`commerce:category`, `commerce:add`, `restaurant:pick_time`, …) used `crm:`/`commerce:`/`restaurant:` — app and template names, not features — so every tap on them silently fell back to the main menu. The exact same class of bug the appointments increment had already found and fixed once, in a different app. | Renamed every affected sub-route to its real owning feature slug: `feedback:rate`, `product_catalog:category`/`product_catalog:product`, `cart_orders:add`/`cart_orders:checkout`, `table_reservation:pick_time`/`table_reservation:confirm`. Top-level routes already declared in a manifest's `menu` tuple (`commerce:catalog`, `commerce:cart`, `restaurant:reserve`) were untouched — they resolve by manifest lookup, not the fallback, and renaming them would have broken the Phase 2 preview catalogue that already hardcodes those exact strings. |

**Decisions made during implementation:**

| Decision | Reason |
|---|---|
| Table reservations have no double-booking guard | Unlike a staff member's calendar, a table reservation has no inventory row (no "how many tables, what capacity") to exclude against yet — building a real exclusion constraint for a resource this platform does not model would be guessing at a schema. Recorded honestly as a gap below rather than a fake capacity check. |
| `apps.crm.models.Feedback` is its own table, not a `Lead` with a repurposed field | A star rating and an enquiry are different objects with different lifecycles (a lead has a status and a pipeline; feedback does not); forcing one into the other's shape to avoid a second small table would have been the wrong kind of economy. |
| "Add to cart" only renders when the bot has actually bought `cart_orders` | `cart_orders` `requires=("product_catalog",)`, not the other way around — a shop can sell `product_catalog` alone (browse, then contact to buy) without `cart_orders`. Showing the button regardless would let a customer tap into a checkout flow the business never paid to offer. |
| `apps.crm` and `apps.commerce` share the `BotViewSet` action pattern established for appointments, rather than getting their own top-level viewsets | Every resource here (leads, products, orders, reservations) is inherently bot-scoped — nesting under the bot matches FAQ, business-profile and appointments exactly, instead of introducing a second convention for no reason. |

**Not built in Phase 7** (deliberate, across the whole phase): `custom_menu` — offered as
an extra by every single template, but with no `menu` entry, no preview steps and no
handler ever written for it, in any phase. Every other feature had at least a Phase 2
preview to build toward; this one has none, which makes it a real, separate feature (a
small dashboard-authored page/button system) rather than one more handler to bolt on.
Also deferred: table capacity limits (above), a customer-facing order-history view
inside the bot (order and reservation management is dashboard-only), and product images
(`Product` has no image field — DATABASE.md's schema allows for one, but file upload
validation for it is `apps.core.files`' existing machinery applied to a new surface, not
new design, and didn't justify the scope here).

---

## Phase 8 — AI *(parallel with P9)* ✅ **COMPLETE**

Provider abstraction (Anthropic default), knowledge base ingestion, pgvector embeddings,
retrieval-grounded answering with explicit "I don't know" behaviour, custom instructions,
per-tenant token budgets and hard caps, admin model configuration, AI pricing.

**Exit:** the AI answers only from configured business knowledge, and a tenant cannot exceed
its budget.

### Implementation notes

`apps.ai` already existed manifest-only since Phase 2 (`AI_ASSISTANT` requiring
`("business_profile", "faq")`, `AI_KNOWLEDGE_BASE` requiring `AI_ASSISTANT` and file
uploads) — this phase gave it real models, services, a bot handler, a provider
abstraction, and a dashboard panel, following the exact layered pattern every Phase 7
module used (models → services → handlers → admin → API → migrations → tests).

**Two tiers, and only one of them needed pgvector.** `ai_assistant` grounds every answer
in the business profile plus every active `FaqEntry`, stuffed directly into the system
prompt — a small business's profile and FAQ list comfortably fits in one prompt, so
retrieval would have been over-engineering for it. `ai_knowledge_base` (requires
`ai_assistant`) is where pgvector actually earns its place: uploaded documents can be too
large to stuff whole, so they're chunked at ingest time, embedded, and only the
top-matching chunks are retrieved per question (`KnowledgeChunk`, cosine search via
`pgvector.django.CosineDistance`). Either way the system prompt tells the model, every
time, to answer *only* from what it was given and to say so plainly when the context
doesn't cover the question — the explicit "I don't know" behaviour the exit criterion
asks for. A cheaper gate sits in front of the model call itself: if a bot has no grounding
at all (blank profile, no FAQ, no matching chunks), the provider is never invoked — there
is nothing it could honestly answer from except its own training data, which is exactly
what "answers only from configured business knowledge" forbids.

**No paid embeddings provider.** Anthropic's Messages API has no embeddings endpoint of
its own — Anthropic's own docs point customers at a separate provider (Voyage AI) for
that. Rather than wire in a second, network-dependent paid provider for a feature this
project needs to build and test without live API keys, `apps/ai/embeddings.py` embeds
with a deterministic, dependency-free hashed bag-of-words (a signed feature-hashing
scheme, the same idea behind scikit-learn's `HashingVectorizer`): the same text always
embeds to the same vector, and two texts sharing literal vocabulary land closer together
under cosine distance. That's enough to exercise the real pgvector storage, `HnswIndex`,
and retrieval path end-to-end — proven by a test that ingests two unrelated documents and
asserts the right one is retrieved for a given question — but it is *keyword* overlap,
not semantic understanding; `RETRIEVAL_MAX_DISTANCE` is calibrated loose (0.9) to compensate.
Swapping in a real embeddings API means replacing `embed_text()` alone — nothing else in
the app depends on how the vector was produced.

**Budgets are enforced per bot, not aggregated across a tenant's bots.** `ai_assistant` is
purchased per bot (`BotFeature`), like every other feature in this codebase — a tenant
running three bots pays for AI on each independently and each has its own budget, exactly
matching how every other paid feature in this SaaS is scoped. `AiConfiguration` carries an
optional per-bot override (`monthly_token_budget`); with none set, the platform default
(`settings.AI_DEFAULT_MONTHLY_TOKEN_BUDGET`) applies. Either way the effective figure is
clamped to `settings.AI_HARD_MONTHLY_TOKEN_BUDGET_CAP` — a ceiling nobody can raise past,
even by misconfiguration, satisfying "hard caps" as a distinct concept from the
customer-visible, customer-editable budget.

**Admin model configuration** is a `SystemSetting` row (`key="ai.model"`,
`value={"model": "claude-..."}`), not a new model or a redeploy — a platform superuser
edits one row in Django admin to move every tenant onto a different Claude model.
`apps.ai.services.get_configured_model()` reads it, falling back to `settings.AI_MODEL`
(defaults to `claude-haiku-4-5`: this feature answers customer-facing chat messages at
volume under a hard per-bot token budget, not one-off high-stakes generations, so cheap
and fast is the right default — not the highest-capability model).

**AI pricing** reuses the existing add-on quote flow (`POST /bots/{id}/addon-quotes/`,
Phase 6) unchanged — `AI_ASSISTANT.price_keys` and `AI_KNOWLEDGE_BASE.price_keys` were
already wired into the pricing catalogue back in Phase 2 alongside every other feature's
price keys; there was nothing AI-specific left to build here.

### Verified 2026-08-16

689 backend tests pass against PostgreSQL 16 (up from 649 after Phase 7 — 40 of them
new, in `tests/test_ai.py`); `check` clean; `next build` and `tsc --noEmit` clean. The
`0001_initial` migration (including `VectorExtension()`, `HnswIndex`, and every table) was
applied to a live Postgres 16 + pgvector container, not just exercised by the test
database. Every new dashboard endpoint (`ai-configuration` GET/PATCH, `ai-usage`,
`ai-documents` GET/POST/DELETE) was also driven live against a running `manage.py
runserver`, including the 403 a knowledge-base document upload gets on a bot that hasn't
bought `ai_knowledge_base`.

**Real bugs, found and fixed while building this** (caught by this phase's own tests):

| Bug | Fix |
|---|---|
| `effective_budget()` used `config.monthly_token_budget` truthily: `if config.monthly_token_budget else None`. A customer setting their budget to exactly `0` — the obvious way to hard-block the assistant immediately — is falsy in Python, so it silently fell through to the platform default instead of blocking anything. | Check `is not None` instead of truthiness, so `0` is respected as a real, deliberately-zero budget. |
| `_business_context_block()` unconditionally emitted `f"Business name: {name}"` even when `name` was empty — so a bot with a genuinely blank profile (no display name, no `bot.name`) still produced a non-empty context block (just a blank value after the colon), which meant the "nothing configured → never call the provider" gate could never actually trigger for such a bot. | Only emit the line when `name` is non-empty, matching every other field's existing "only include what's actually there" pattern in the same function. |

### Decisions made during implementation

| Decision | Reason |
|---|---|
| Budget scope is per bot, not per tenant | See "Implementation notes" above — matches the purchase granularity (`BotFeature`) every other feature in this codebase already uses; a tenant-level aggregate would need new cross-bot infrastructure this platform doesn't otherwise have. |
| Local deterministic embedding instead of a real embeddings API | No embeddings endpoint exists on the Anthropic Messages API; adding a second paid provider (Voyage AI) for one phase, in an environment this project needs to build and test without live keys, wasn't justified. Documented as a swap-in point, not hidden. |
| Document ingestion accepts plain text only (pasted, or `.txt`) | Parsing PDF/DOCX would mean new heavy dependencies (`pypdf`, `python-docx`) for a concern orthogonal to what this phase is actually about — retrieval, budgets, and grounded answering. Recorded as a gap below rather than silently scoped out. |
| `/ask` is not feature-gated at the router's command branch | `apps.bot_runtime.router.resolve()`'s command branch (branch 2) never checks `ctx.has_feature(...)` for *any* module's commands — `/contactus`, `/reserve`, `/catalog` and every other business-module command have had this same latent gap since Phase 7 and earlier. The free-text fallback (branch 5, the path a customer actually uses without prior knowledge of a slash command) *is* properly gated on `ai_assistant`. Fixing the command branch is a router-wide change affecting every business module, not an AI-specific one — out of scope for this phase, and not new to it. |

### Not built in Phase 8

PDF/DOCX parsing for knowledge-base documents (plain text only, see above); a real
embeddings provider (the local hashed embedding is a documented, swappable stand-in); a
dashboard "test the assistant" endpoint (testing happens through the actual bot, matching
how every other module in this codebase is verified — there is no dashboard-side preview
simulation anywhere else either); per-message conversation history across turns (each
question is answered independently — the router's free-text fallback re-invokes `ai:ask`
for every message regardless, so there was no natural place to accumulate state, and nothing
in the exit criterion asked for multi-turn memory).

---

## Phase 9 — Subscriptions *(parallel with P8)* ✅ **COMPLETE**

Plans, subscription records, expiry scheduler, grace period, suspension that genuinely
disables the runtime and removes the webhook, reactivation, admin manual management, renewal
reminders.

**Exit:** an expired subscription moves `ACTIVE → GRACE_PERIOD → SUSPENDED` on schedule and
the bot actually stops responding.

### Implementation notes

`apps/subscriptions/` existed only as an empty placeholder directory before this phase —
genuinely greenfield, but landing on ground Phase 3 had already prepared: the order state
machine (`apps.orders.domain.state_machine`) already had `ACTIVE ⇄ SUSPENDED` edges gated
on a `subscriptions.manage` scope nobody had used yet, `BotStatus`/`BotPlatformInstance.Status`
already had a `SUSPENDED` choice, the notification catalogue already had `order.suspended`
wired to real copy, and `apps.bot_runtime.context.load_instance` already refused a webhook
for any instance whose `status` isn't `ACTIVE` — this phase's exit criterion's second half
("the bot actually stops responding") already worked, for any instance whose status ever
actually became non-`ACTIVE`. Nothing had ever set it. That is the gap this phase closes.

**No separate `Plan` model.** This platform prices per feature, à la carte
(`PriceList`/`PriceVersion`, Phase 2) — that catalogue already *is* the plan. A
`Subscription` doesn't re-describe what was purchased; it tracks the one thing that
genuinely didn't exist anywhere: the billing *cycle* — when the current period ends,
whether a lapsed bot is still inside its grace window, and when it was actually suspended.
`Subscription.monthly_amount_minor` is seeded from `Order.subtotal_recurring_minor` at
first activation (`apps.provisioning.saga.step_activate`) and incremented the same way
when an add-on order with its own recurring items goes live (`step_addon_activate`) — both
hooks are one new line each in a saga that already ran.

**Three records move together, for three different reasons.** `Subscription.status` is
what this phase's own services (and the expiry sweep) act on and query. `bot.origin_order`'s
status is mirrored alongside it purely so the *existing* order-lifecycle audit trail
(`OrderEvent`) and notification catalogue (`order.suspended`, `order.active`, wired since
Phase 3) keep firing unchanged — `transition_order()` already publishes `order.{status}`
on every move, so adding `GRACE_PERIOD` as a state meant the grace-period notification
(new: `notify.subscription.grace_period.*`) was the only one actually new; suspension and
reactivation reuse Phase 3's copy verbatim. Neither of those two is what stops the bot,
though — `Bot.status` / `BotPlatformInstance.status`, flipped in the same transaction, are
what `load_instance` actually checks on the ingress path, and are the only fields that
matter for "the bot actually stops responding." Removing the webhook
(`provisioner.delete_webhook(token)` — a method that already existed on every provisioner,
never called by anything) happens in the same loop, best-effort: if a platform call fails,
the instance is still marked `SUSPENDED` and traffic still stops immediately, because that
half of the guarantee runs through the database, not the network call.

**Renewal is a staff action, not a self-serve purchase.** This platform has no live
payment gateway — Phase 3's manual receipt-review flow is the only payment path that
exists. A self-serve "renew now" flow would need a new `OrderKind`, a new quote-building
path, and a saga branch that skips provisioning entirely to jump `PAID → ACTIVE` — three
new pieces of machinery duplicating Phase 3's for no new architectural lesson. `renew()`
is instead a deliberate staff action (Django admin, mirroring `apps.payments.admin`'s
approve/reject queue exactly), gated on the same `subscriptions.manage` scope the state
machine already named. It both clears a lapse (extends the period, reactivates a suspended
bot's runtime and webhook) and simply extends an already-`ACTIVE` subscription — one
function, since in practice "staff confirms payment was received" is the same action
either way.

### Verified 2026-08-16

715 backend tests pass against PostgreSQL 16 (up from 689 after Phase 8 — 26 of them new,
in `tests/test_subscriptions.py`); `check` clean; `next build` and `tsc --noEmit` clean;
`lint-imports` reports the services/domain-layering contract KEPT. Both new migrations
(`subscriptions.0001_initial`, `orders.0006_alter_order_status`) were applied to a live
Postgres 16 container, not just the test database. Verified directly rather than only
through the service layer: a suspended instance's `load_instance()` lookup actually
returns `None` (a real assertion in `TestGracePeriodAndSuspension`, not just "status was
set"); the Django-admin renew/suspend confirm screens render and their POST actions
actually move the record, through Django's real URL routing and templates (mirroring
`test_admin_operations.py`'s existing pattern for the payment-review queue); the dashboard
API's `subscription` field was checked live against a running `manage.py runserver` — the
seeded demo bot correctly returns `subscription: null` there, since `seed_demo` creates it
directly rather than through `provisioning.saga.step_activate`, and the field is nullable
for exactly this reason (a bot from before this phase, or seed data, has no subscription
row; the frontend already treats `null` as "don't show the panel").

**No bugs in the delivered code this time** — the state machine, notification catalogue,
and `load_instance` gate this phase builds on were already correct from earlier phases,
and the new service functions passed on the first full run against real Postgres. Two
mistakes did surface, both in the *tests*, not the app: the first draft of the
staff-renewal tests passed a tenant-role `user` fixture as the actor for a `GRACE_PERIOD →
ACTIVE` / `SUSPENDED → ACTIVE` transition — `state_machine.check()` correctly rejected it
(a tenant owner has no platform-staff scopes at all; `subscriptions.manage` belongs to
`StaffRole.FINANCE_AGENT`), which is the permission check working as designed against an
under-specified test, not an app bug. Fixed with a proper `finance_staff` fixture. Second,
the draft tests called `fake_transport.calls(...)` and a nonexistent `.reset_calls()` —
`FakeTransport.calls` is a plain list and `.called(method)` is the boolean check; fixed to
match the fake's actual (already-established) interface.

### Decisions made during implementation

| Decision | Reason |
|---|---|
| No `Plan` model | See "Implementation notes" above — this platform's à-la-carte per-feature pricing already is the plan; a `Subscription` only needed to own the billing cycle, which genuinely didn't exist anywhere. |
| A fixed 30-day billing period, not calendar-month-exact | Simple, deterministic, and easy to test; this is a manually-billed SaaS with no live payment gateway to reconcile against a real calendar billing date in the first place. |
| Renewal is staff-driven (Django admin), not a self-serve purchase flow | See "Implementation notes" above — a self-serve flow would duplicate Phase 3's manual-payment machinery (new `OrderKind`, new saga branch) for no new lesson; the exit criterion is about the *downward* path (expiry → suspension) and doesn't require it. Recorded as a gap below, not hidden. |
| Suspension mirrors to `bot.origin_order`, tolerating an order that isn't where expected | An add-on order or a manually-adjusted order could leave `bot.origin_order.status` somewhere the state machine has no edge from to `SUSPENDED`/`GRACE_PERIOD`/`ACTIVE`. `_mirror_to_order()` checks `state_machine.find(...)` first and silently skips the order-side move rather than raising — the subscription and runtime state changes (the two that actually matter) must never be blocked by secondary bookkeeping being in an unexpected state. |
| `rotate_webhook_secret` promoted from a saga-private helper (`_rotate_webhook_secret`) to a public one | Reactivation needs the exact same secret-rotation logic provisioning already uses (issue fresh, retire anything older than the two most recent) — reimplementing it a second time risked the two copies drifting on a security-sensitive path. A one-line rename, not a new abstraction. |

### Not built in Phase 9

A self-serve renewal purchase flow (customer pays, subscription renews automatically —
see the decision above; today a staff member renews manually via Django admin, the same
manual-trust model Phase 3 already established for payment approval); per-tenant
subscription aggregation across a tenant's multiple bots (each bot has its own
subscription, matching the purchase granularity every other feature in this codebase
uses — a tenant with three bots manages three subscriptions, not one); prorated billing
for an add-on purchased mid-period (an add-on's recurring amount is simply added to the
next full period, not prorated for the partial month remaining — a real product decision
a live payment gateway would need to answer, and this platform has none).

---

## Phase 10 — Production hardening ✅ **COMPLETE**

Structured JSON logging with trace IDs, error tracking, metrics and dashboards, PostgreSQL
RLS, backup and restore drill, rate-limit tuning, job retry/DLQ policy, health checks,
query and cache optimisation, load test at target bot count, runbooks, deployment guide.

**Exit:** documented restore from backup, load target met, runbooks exist for every
`ProvisioningJob` failure code.

### Implementation notes

**PostgreSQL RLS needed a second database role to mean anything at all.** The app's DB
user is the tables' owner (it ran the migrations) — PostgreSQL unconditionally bypasses RLS
for a superuser or a table's own owner, so enabling RLS on that same connection would have
been pure security theater, silently doing nothing. `apps/core/migrations/0002_row_level_security.py`
creates a second, deliberately unprivileged role (`botbuilder_app`: `NOLOGIN NOSUPERUSER
NOBYPASSRLS`, DML-only grants, never ownership); `apps.core.tenant_session` drops every
serving connection into it via `SET ROLE` on Django's `connection_created` signal, for that
connection's entire lifetime — migrations, a separate process, never do this and keep full
owner privileges, which is what lets them still alter the schema. Each of the 26 tenant-owned
tables gets `FORCE ROW LEVEL SECURITY` and a fail-closed policy:
`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint` — an unset or blank
session variable compares against `NULL`, never true, so an unscoped connection sees zero
rows, not everything. `TenantScopedMixin.initial()` (not `get_queryset()` — DRF calls
`initial()` for every action including a bare `create`, which never calls `get_queryset()`
at all) is what arms the session variable before the first query of any request.

**Structured JSON logging had to work for the 99% of this codebase that calls
`logging.getLogger(__name__)`, not just code that calls `structlog.get_logger()`.**
`structlog.stdlib.ProcessorFormatter`'s `foreign_pre_chain` is the mechanism that applies
structlog-style processors to plain stdlib log calls — `structlog.configure()` alone only
makes `structlog.get_logger()` itself usable. Verified live with a throwaway script showing
both call styles rendering as correctly-shaped JSON through the same pipeline, not assumed
from the library's docs.

**Trace-ID propagation from an API request into the Celery task it triggers** uses Celery's
own message headers: `before_task_publish` stashes the current `request_id` into the
outgoing message on the publishing side; `task_prerun` reads it back out on the worker side.
Verified with a genuine live round-trip — dispatch a task with a known id, start a real
worker, confirm the id shows up in the worker's own log line — which is what surfaced
`worker_hijack_root_logger` (Celery's default silently replaces Django's entire `LOGGING`
config, including this propagation, for every worker process; one line,
`worker_hijack_root_logger=False`, fixes it). An isolated unit test of the signal handlers
would not have caught this — only running a real worker did.

**Job retry/DLQ policy meant classifying each task, not applying one rule everywhere.**
`provision_order` and `deliver_notification`'s email path already fully absorb their own
failures into a domain status field (`ProvisioningJob.error_code`, `DeliveryStatus.FAILED`)
with their own recovery paths (the admin's Retry button; nothing, respectively, since a
failed email isn't worth auto-retrying) — their declared `max_retries` had never once been
exercised, since nothing inside either task ever called `self.retry()`; removed, with a
comment explaining why re-adding it would race the domain-level recovery instead of
replacing it. `process_update` and `deliver_notification`'s surrounding I/O (DB, and for
`process_update` the Redis-backed session store) genuinely can fail transiently in a way
nothing else sweeps up quickly — both now declare a narrow `autoretry_for` scoped to exactly
those transient exception types, not a blanket catch-all, so a real bug in a handler still
surfaces immediately. `FailedTaskLog` (populated by the `task_failure` signal, which only
fires once a task is done retrying) is the cross-cutting DLQ underneath all of that — one
durable, admin-visible row per genuine terminal failure, independent of whatever
domain-specific tracking a given task already has. Auditing every task this way also
surfaced that six sweep/safety-net tasks — including `retry_outbound`, **the only thing
that ever retries a rate-limited outbound message** — existed in code, with docstrings
describing them as periodic, but had never actually been entered into
`CELERY_BEAT_SCHEDULE`; see DEPLOYMENT.md §5.

**A query-optimization audit found four real N+1s**, the worst being two list endpoints
where a `prefetch_related` existed on the queryset but a serializer method silently
defeated it by chaining `.filter()`/`.order_by()` onto the related manager — only a bare
`.all()` reads Django's prefetch cache; any further queryset method re-queries per row. Both
fixed (CRM leads' notes/tags; the bot dashboard's features/provisioning-steps), plus two
straightforward missing `select_related`/`prefetch_related` (product catalogue, staff
list), each with a `django_assert_max_num_queries` regression test.

### Verified 2026-08-17

759 backend tests pass against PostgreSQL 16 (up from 715 after Phase 9), across 8 new test
files this phase (RLS enforcement, tenant-session reset semantics, structured logging,
Celery signal propagation, job retry/DLQ config, query-count regressions, runbook
completeness) plus additions to existing ones. 3 pre-existing, unrelated failures in
`tests/test_appointments.py` (a `_next_weekday()` helper that assumes "the next occurrence
of this weekday" always has a full day of working hours ahead of it — false on a Monday
afternoon, which is when this phase's final full-suite run happened to land) — confirmed
unrelated by running them in isolation (they fail identically with none of this phase's code
present) and out of scope for this phase's work.

Beyond the test suite: the RLS migration and role were applied to a live Postgres 16
container, not just the test database, with role attributes and per-table policy presence
checked directly via `psql`. A genuine live Celery worker was started to verify JSON
logging and trace-id propagation reach real worker output, not just pass in-process
signal-handler tests. A full backup → restore drill ran against the dev container
(`scripts/backup.sh` / `restore.sh`), verified by table count, spot-checked row counts, and
— specifically — that RLS state itself survives a restore (26/26 tables), then torn down;
see DEPLOYMENT.md §6. A load test ran against a real running server (not
`CELERY_TASK_ALWAYS_EAGER`) at three concurrency levels; see DEPLOYMENT.md §8 for the
numbers and honest caveats about dev hardware.

### Real bugs found and fixed

**A severe, silent RLS bypass**, caught only by testing the request lifecycle live, not by
reading the code. The `request_finished` handler that resets per-request session state
originally also ran `RESET ROLE` — which reverts to `session_user`, i.e. the *connecting*
role. But the privilege drop happens once, on `connection_created`, which does not fire
again for a connection Django is reusing (`CONN_MAX_AGE`, on by default in this project).
So the original code silently restored full owner privileges — RLS completely bypassed —
for every request after the first one on any pooled connection. Caught while chasing an
unrelated test failure (a `/metrics`/`/healthz` test hit pytest-django's "database access
not allowed" guard, which traced back to this same handler unconditionally opening a
cursor). Fixed by never resetting `ROLE` in the per-request handler at all — only the
per-request tenant variable — and by skipping the reset's database round trip entirely when
the request never scoped a tenant in the first place, so a deliberately DB-free view like
`/healthz` genuinely stays DB-free even on a connection a prior request left open. Verified
live with a script that simulates two requests sharing one physical connection and confirms
the role stays dropped for both; now has a permanent regression test
(`tests/test_tenant_session.py`).

**A `/metrics` scrape could hang indefinitely on a broker outage.** The Celery
queue-depth gauge connects to Redis directly at scrape time; `redis-py` does not time out
DNS/connect/read by default, and an unreachable broker (a misconfigured `CELERY_BROKER_URL`,
tried live during development) blocked the request with no bound. Fixed with an explicit
1-second `socket_connect_timeout`/`socket_timeout` — a monitoring endpoint must never be
able to hang the process monitoring is supposed to be watching.

**A load-test client artifact, worth recording because it cost real debugging time.**
Creating a fresh `httpx.Client()` per request from a `ThreadPoolExecutor` on Windows adds a
consistent ~1 second delay per client (proxy autodetection), which under concurrent load
manifested as uniform request failures that looked exactly like a server-side capacity
problem — chased for a while as one before four genuinely parallel `curl` processes (real
OS concurrency, no shared Python client) proved the server was fine in under 100ms. Not an
application bug; recorded so `scripts/load_test_webhook.py` disables it
(`trust_env=False`) and reuses one shared client, and so the next person load-testing on
Windows doesn't lose the same time to it.

### Decisions made during implementation

| Decision | Reason |
|---|---|
| A second Postgres role (`botbuilder_app`), not RLS on the existing connection | The existing DB user is a superuser and the tables' owner — RLS is unconditionally bypassed for both, so there was no other way to make RLS enforce anything at all. |
| `SET SESSION` (`set_config(..., false)`) for the tenant variable, not `SET LOCAL` | This project already runs with `ATOMIC_REQUESTS = False` — there is no guaranteed enclosing transaction for a whole request for `SET LOCAL` to be scoped to. Explicit reset on `request_finished` covers the pooled-connection leak risk `SET LOCAL` would otherwise exist to prevent. |
| Never `RESET ROLE` per-request | See "Real bugs" above — the privilege drop is connection-lifetime by design; resetting it per-request silently disables RLS on every reused connection. |
| Dead `max_retries` removed rather than "fixed" into real retries | For tasks whose failures are already fully absorbed into a domain status field with their own recovery path, a Celery-level retry would race that mechanism, not improve it — see "Implementation notes" above. |
| `FailedTaskLog` as a separate, cross-cutting DLQ rather than extending each task's own failure tracking | Different question, different audience: a task's own domain tracking answers "why is this one business object stuck"; `FailedTaskLog` answers "which Celery tasks are dying" platform-wide, for an operator who doesn't yet know which domain model to go look at. |
| `waitress`, not `gunicorn`, for the Phase 10 load test | gunicorn does not run on Windows at all (relies on `os.fork()`); `waitress` is a real, production-grade WSGI server, used here only as a Windows-compatible stand-in for measurement — production still runs gunicorn per DEPLOYMENT.md §5, unchanged. |
| Load test reports a concurrency curve, not a single pass/fail number | The 50 ms target is met at concurrency 10 and missed above it on this specific dev setup (one unpooled Postgres instance) — reporting only the failing higher-concurrency number would be dishonest about where the application logic itself stands; reporting only the passing one would hide a real, worth-knowing capacity boundary. |

### Not built in Phase 10

Alerting itself — the metrics, gauges, and log fields an alerting backend would consume all
exist (DEPLOYMENT.md §7), but nothing pages anyone yet; wiring Prometheus/Grafana alert
rules or an on-call integration is infrastructure setup outside this codebase, not
application code. WAL archiving and a nightly backup schedule — `scripts/backup.sh`/
`restore.sh` are the proven mechanism (a real drill ran against them), but the cron/systemd
timer and continuous WAL shipping that would make the stated RPO/RTO targets real in
production are a deployment-infra step, not yet wired up anywhere but locally. A connection
pooler (PgBouncer) in front of Postgres — the load test's own results are the argument for
why production needs one; provisioning and configuring it is infrastructure, not this
phase's scope. Rate-limit tuning turned out to need no changes — the existing scoped
throttles (`auth`, `upload`, plus the env-configurable defaults) were already reviewed and
found adequate; recorded as a deliberate "no change" rather than silently skipped.
