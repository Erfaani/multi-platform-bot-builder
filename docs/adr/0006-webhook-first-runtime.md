# ADR-0006 — Webhook-first runtime with a shared dispatcher

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Spec §21 requires one platform serving all bots, and §58 explicitly forbids "one process per
bot". Long polling requires an open connection per bot: at 1,000 bots that is 1,000
concurrent loops, which contradicts both.

## Decision

**Webhooks are the production ingress.** One route,
`POST /webhooks/{platform}/{bot_public_id}/`, authenticated by a per-bot secret (Telegram's
`secret_token` header where available, otherwise HMAC over the raw body plus an unguessable
UUID path), compared in constant time.

The ingress view does exactly three things: authenticate, persist the raw update, enqueue.
No business logic, no outbound calls, target p99 under 50 ms. Idempotency comes from a unique
`(bot_platform_instance_id, platform_update_id)`; a conflict means redelivery, so it returns
`200` and drops.

A **sharded multiplexed poller** exists only for local development and for bots whose
platform or deployment cannot receive webhooks: N workers, each polling a hash-slice of bot
IDs — never one process per bot.

All outbound traffic goes through a single **Outbound Gateway** with Redis token buckets per
bot and per chat. It is the only code permitted to call a platform HTTP API.

## Consequences

**Positive.** Runtime cost scales with *message volume*, not bot count — an idle bot costs
nothing. Backend processes stay stateless and horizontally scalable. Durable updates mean a
worker crash loses nothing, and a bad deploy can be replayed. Centralising sends makes rate
limiting, retries, `retry_after` handling, auditing and the preview adapter all fall out of
one place instead of being scattered across features.

**Negative.** A public HTTPS endpoint with a valid certificate is mandatory, so local
development needs a tunnel or the polling fallback. Per-bot webhook registration becomes a
provisioning step that can fail and must be idempotent and retryable. Secret rotation needs
an overlap window. Debugging is asynchronous — mitigated by `inbound_update` /
`outbound_message` rows being the durable, queryable trail when a customer reports "my bot
didn't reply".
