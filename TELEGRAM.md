# TELEGRAM INTEGRATION

Status: **Phase 0 — design** · Implemented in Phase 4 · Last updated: 2026-08-10

---

## 1. The constraint that shapes the product

**There is no Bot API method to create a bot.** Bot creation happens only through a
conversation with `@BotFather`, a user-facing bot. The Bot API can *configure* a bot it
already has a token for; it cannot bring one into existence.

Consequences:

- Fully automated "customer never touches anything" provisioning is **not possible** through
  the official API.
- A bot's `@username` is fixed at creation by BotFather and **cannot be changed** by any API
  method. `setMyName` changes the display name only.
- Automating BotFather requires driving a *user account* over MTProto, which is fragile,
  rate-limited and carries a real ban risk for the driving account.

This is R-01 in [docs/00-ANALYSIS.md](docs/00-ANALYSIS.md) and it needs an explicit product
decision before Phase 4.

## 2. Provisioning strategies

Implemented behind one `ProvisioningStrategy` interface; the order records which was used.

### A. Bot Pool — *"Instant" tier, default*

Operations pre-creates bots with platform-owned usernames and stores the tokens encrypted.
Provisioning assigns an available `bot_pool_entry`, then configures it:

```
setMyName · setMyShortDescription · setMyDescription · setMyCommands (per locale) · setWebhook
```

Fully automatic, completes in seconds, customer does nothing.
Trade-off: a generic `@username`. Pool depth is monitored and alerts below threshold.

### B. Guided Token Handoff — *"Custom username" tier*

The dashboard walks the customer through BotFather (copy-paste blocks, screenshots, ~60 s).
They paste the token once. We `getMe` to validate, encrypt, take over the webhook, and never
display it again. The customer keeps their vanity username; we keep full operational control
— which is what spec §24 actually requires.

Validation on intake: token shape `^\d+:[A-Za-z0-9_-]{30,}$`, `getMe` succeeds, `is_bot` is
true, the token fingerprint is not already registered to another tenant, and
`getWebhookInfo` shows no conflicting third-party webhook (warn and offer takeover).

### C. Assisted MTProto — *operations only, flagged off*

A supervised tool that drives BotFather from a platform-owned account to **refill the pool**.
Never on a customer request path. Gated by `PROVISIONING_MTPROTO_ENABLED`, rate-limited,
with a manual fallback queue. Keeps ToS and ban risk inside operations, not on a paid order.

## 3. Webhooks

```
setWebhook(
  url          = https://tg.<domain>/webhooks/telegram/{bot_public_id}/,
  secret_token = <per-bot secret, 1–256 chars of A-Za-z0-9_->,
  allowed_updates = ["message", "callback_query", "my_chat_member", ...],
  max_connections = 40,
  drop_pending_updates = true      # on first activation only
)
```

- Telegram sends the secret back in `X-Telegram-Bot-Api-Secret-Token`; we compare in
  constant time. Two secrets are accepted during a rotation overlap window.
- Public HTTPS on port **443, 80, 88 or 8443** with a valid certificate is mandatory.
- `getUpdates` and `setWebhook` are mutually exclusive — polling is development-only.
- Telegram retries on non-2xx, so the ingress returns `200` as soon as the update is durably
  stored (see [BOT_RUNTIME.md](BOT_RUNTIME.md) §2).
- `deleteWebhook` on suspension, archive, and subscription suspension.

## 4. Rate limits (enforced by our gateway, not discovered by getting throttled)

| Scope | Limit |
|---|---|
| Global per bot | ~30 messages/second |
| Per chat | ~1 message/second |
| Per group | ~20 messages/minute |
| Bulk notifications | keep well under the global limit |

`429` responses carry `parameters.retry_after`, which the gateway honours exactly. Reminder
and broadcast traffic runs on a lower-priority queue so it cannot starve interactive replies.

## 5. Capability manifest

```python
Capabilities(
    inline_keyboards=True, reply_keyboards=True,
    max_buttons_per_row=8, media_groups=True,
    message_editing=True, web_app=True,
    max_text_length=4096,
)
```

Other limits the adapter enforces so features never have to: caption 1024 chars, callback
data 64 bytes (we store a short signed key in Redis and put the key in the payload), file
download 20 MB, upload 50 MB (a self-hosted Local Bot API server lifts this if it ever
matters).

## 6. Adapter responsibilities

Parse `Update` → `InboundEvent`; render `Reply` → Telegram payloads (inline vs reply keyboard
per context, chunking over 4096 chars, `MarkdownV2` escaping); map errors to typed exceptions
(`BotBlockedByUser`, `ChatNotFound`, `TooManyRequests`, `InvalidToken`, `WebhookConflict`);
set commands per locale via `setMyCommands(language_code=…)`.

The adapter is the **only** place `python-telegram-bot`/raw HTTP appears. Nothing else
imports a Telegram symbol.

## 7. Egress

All calls go through the platform's egress profile (`base_url`, `proxy_url`, timeouts,
retries) from configuration — never a hard-coded `api.telegram.org`. Telegram traffic runs on
the `worker-telegram` queue so it can be scheduled onto hosts with appropriate network
reachability (analysis R-03).

## 8. Telegram Builder Bot (spec §45)

A single platform-owned bot: `/start`, Create Bot, My Bots, My Orders, Payment Status,
Support, Language. It is a **client of the same REST API** as the website — it holds no order
logic of its own (spec rule 61.1).

Account linking uses a single-use, short-TTL nonce delivered as a deep link
(`t.me/<builder_bot>?start=<nonce>`), issued from an authenticated web session and consumed
by the bot. Never link by phone or email alone — that would be an account-takeover path.

Quotes are shared, so an order started in Telegram is resumable on the website and vice
versa (spec §18, §47).

## 9. Security

Tokens encrypted at rest with envelope encryption, never serialized, never logged (a logging
filter redacts token-shaped strings), never visible to any customer or staff role. Webhook
secrets are per-bot and rotatable. Telegram Login payloads, if enabled later, must be verified
by HMAC-SHA256 against the bot token with an `auth_date` freshness check.

## 10. Open items before Phase 4

- [x] Product sign-off on the pool vs. handoff tiering — **both approved 2026-08-11**
      (ADR-0002). Tier pricing still to be set, but it is data, not code.
- [ ] Legal review of storing and using customer-supplied bot tokens (ToS clause).
- [ ] Decide the pool username scheme and initial depth.
- [ ] Confirm the production hostname and TLS termination for the Telegram webhook endpoint.
