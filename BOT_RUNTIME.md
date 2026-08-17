# BOT RUNTIME

Status: **Implemented for Telegram in Phase 4** · Last updated: 2026-08-11

Built as described, with these deltas recorded during implementation:

- Saga steps carry the order status they belong to, so the order walks
  `PROVISIONING → CONFIGURING → DEPLOYING → ACTIVE` as work progresses (F-12).
- Route→feature ownership comes from the manifests, not from the route namespace (F-13).
- Callback payloads are HMAC-signed **per bot instance** and must fit Telegram's 64-byte
  `callback_data` cap; `encode()` raises at build time rather than letting the platform
  reject the button at runtime.
- `AWAITING_CUSTOMER` is a first-class saga state for the tier-B token handoff — a resting
  state, never timed out into a failure (ADR-0002).
- The polling fallback (§9) and the Telegram builder bot are **not yet built**.

One runtime serves every bot on the platform. There is **no process, container, database or
deployment per customer** (spec §21, §58). A bot is a set of rows.

---

## 1. Pipeline

```
 Platform ──► POST /webhooks/{platform}/{bot_public_id}/
                     │
                     │  ingress view: authenticate secret · persist raw · enqueue
                     │  no business logic, no outbound calls, target p99 < 50 ms
                     ▼
              inbound_update (durable)  ──► Celery queue (per platform)
                     │
                     ▼
              ┌──────────────────────────────────────────┐
              │            Dispatcher                    │
              │ 1. resolve BotContext (cached)           │
              │ 2. adapter.parse() → InboundEvent        │
              │ 3. load Session (Redis → DB)             │
              │ 4. resolve locale                        │
              │ 5. route: FSM state, else menu route     │
              │ 6. feature handler → Reply               │
              │ 7. persist session                       │
              │ 8. adapter.render() → OutboundMessage[]  │
              │ 9. emit analytics + domain events        │
              └───────────────────┬──────────────────────┘
                                  ▼
                        Outbound Gateway
              (per-bot + per-chat token buckets, retries)
                                  ▼
                          Platform HTTP API
```

**The Outbound Gateway is the only code permitted to call a platform HTTP API.** Feature
handlers return data; they never send anything themselves. That single rule is what makes
rate limiting, retries, auditing and the preview adapter all possible.

---

## 2. Ingress

`POST /webhooks/{platform}/{bot_public_id}/`

1. Look up the instance by `bot_public_id` (cached). Unknown or non-`ACTIVE` → `200` and
   drop (never leak existence, never make the platform retry).
2. Verify the per-bot secret in constant time — Telegram's
   `X-Telegram-Bot-Api-Secret-Token`, or an HMAC-SHA256 header over the raw body where the
   platform has no equivalent. Two secrets may be valid at once during rotation.
3. Enforce body size and JSON depth caps.
4. Insert `inbound_update` with unique `(bot_platform_instance_id, platform_update_id)` —
   a conflict means redelivery, so return `200` immediately and do nothing.
5. Enqueue on the platform's queue. Return `200`.

Suspended subscriptions are rejected at step 1, so suspension actually stops the bot.

## 3. BotContext resolution

Every update resolves to:

```
platform · bot_platform_instance · bot · tenant · configuration
enabled_features (+ per-feature config) · default_locale · timezone · currency
```

Cached in Redis under `botctx:{bot_public_id}:v{configuration.version}`. A configuration
change bumps `version`, which invalidates the key with no broadcast and no stale window.
Target: no database hit on a warm cache, < 5 ms.

## 4. Session & conversation FSM

Multi-step flows (booking, ordering, lead capture) are a **platform-agnostic state machine**:

```
Session(bot, platform, chat_ref, user_ref) = { state, context, locale, expires_at }
```

Redis is the hot copy with a TTL; `bot_session` is the durable copy, so a worker restart does
not lose a half-finished appointment. Handlers are pure-ish: `(event, session, ctx) → (Reply, next_state)`.

Every flow supports cancel/back at any step, and a stale session (default 30 min) resets to
the main menu with an explanatory message rather than silently misinterpreting input.

## 5. Routing

```
if session.state is not IDLE      → the owning feature's state handler
elif event is a command           → command registry (/start, /help, /language, /menu)
elif event is a callback          → route parsed from callback data (signed, versioned)
elif event matches a menu label   → that menu route
else                              → AI fallback if enabled, otherwise main menu
```

Routes are namespaced `feature:action` and come from feature manifests — the router itself
contains no feature knowledge.

## 6. Feature handlers

```python
def handle(event: InboundEvent, session: Session, ctx: BotContext) -> HandlerResult:
    ...
    return HandlerResult(
        reply=Reply(text_key="bot.appointment.select_doctor",
                    choices=[Choice(label_key=..., route="appointment:pick_staff", data={...})]),
        next_state="appointment.awaiting_staff",
        events=[AppointmentStarted(...)],
    )
```

Handlers never touch platform APIs, never emit literal strings (keys only), never query
across tenants, and are unit-testable with no network and no database.

## 7. Outbound Gateway

- Per-bot token bucket (~30 msg/s) and per-chat bucket (~1 msg/s) in Redis — Telegram's
  documented limits, applied before we get throttled rather than after.
- Retries with exponential backoff and jitter; `429` honours the platform's `retry_after`
  exactly.
- Permanent failures (blocked by user, chat not found) mark the `business_contact` inactive
  instead of retrying forever.
- Every send is recorded in `outbound_message` with status and attempt count — this is the
  audit trail and the debugging surface when a customer says "my bot didn't reply".
- Bulk sends (appointment reminders, broadcasts) go through a lower-priority queue so they
  can never starve interactive replies.

## 8. Adapters

Contract in [ARCHITECTURE.md](ARCHITECTURE.md) §4. Each declares a capability manifest; the
core emits abstract `Reply` objects; the adapter renders within its capabilities, degrading
along a fixed ladder (`inline keyboard → reply keyboard → numbered text menu`,
`media group → sequential sends`, `edit → new message`).

Three adapters:

| Adapter | Purpose |
|---|---|
| `telegram` | Production channel |
| `bale` | Production channel |
| `preview` | Renders to JSON for the pre-payment web preview (spec §48) **and** serves as the test double |

The preview adapter is deliberate leverage: it keeps the channel-independence claim
continuously verified instead of aspirational.

All adapters pass the same `tests/conformance/` suite against recorded fixtures — no live
network in CI.

## 9. Polling fallback

Webhooks are the production path. A **sharded multiplexed poller** exists for local
development and for any bot whose platform or deployment cannot receive webhooks: N worker
processes, each owning a hash-slice of bot IDs, polling cooperatively in a loop. Never one
process per bot (spec §58).

## 10. Idempotency & failure

- Update-level: unique `(instance, platform_update_id)`.
- Handler-level: side-effecting actions (create appointment, place order) carry an
  idempotency key derived from `(session, state, update_id)`.
- Send-level: `outbound_message` rows are created before dispatch, so a crash between
  intent and send is visible and recoverable.
- A handler exception logs with `trace_id`, replies with a localized generic error, resets
  the session to a safe state, and increments the bot's error counter. A bot with a high
  error rate is surfaced on the admin System Health panel.

## 11. Provisioning saga

Executed on payment approval (`OrderPaid`), as ordered, individually-idempotent steps:

```
acquire_credential   (pool assign │ token handoff │ flagged MTProto)
verify_get_me        (validate the token, capture username & platform_bot_id)
create_bot_record
apply_configuration  (template defaults + customer's business data)
enable_features      (from order items)
set_commands         (localized command list per supported locale)
set_webhook          (generate secret, register URL)
smoke_test           (synthetic update round-trip through the real pipeline)
activate             (Bot → ACTIVE, Order → ACTIVE, notify customer)
```

Each step is a `provisioning_step` row with its own status, attempt count and idempotency
key. A retry resumes at the first non-`SUCCEEDED` step. Failures record a structured
`error_code` that maps to an operator runbook, and compensation releases any reserved pool
entry. Admin can retry a job from the panel (spec §40).

## 12. Health

Per bot: webhook registered, last update received, last successful send, error rate, queue
lag. Per platform: adapter reachability from each egress profile. Aggregate: queue depth,
failed provisioning jobs, outbound retry backlog — all on the admin dashboard (spec §25).
