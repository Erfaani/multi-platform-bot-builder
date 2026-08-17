# ADR-0002 — Bot provisioning strategy

- **Status:** **Accepted** — both tiers signed off 2026-08-11
- **Date:** 2026-08-10 · **Accepted:** 2026-08-11
- **Supersedes:** the specification's assumption in §20 that bot creation can be automated

## Context

Spec §1 promises the customer will never need to "know bot tokens", and §20 describes
provisioning as "Create Telegram Bot if required".

Neither is achievable as written:

- The Telegram Bot API has **no bot-creation method**. Bots exist only after a conversation
  with `@BotFather`, a user-facing bot.
- A bot's `@username` is fixed at creation and **cannot** be changed by any API call.
  `setMyName` changes the display name only.
- Bale has the same restriction and no documented automation surface.
- Automating BotFather requires driving a *user* account over MTProto: fragile (free-text
  prompts that change), rate-limited, and a genuine ban risk for the driving account.

So the choice is not "automate or not" — it is *where to put the unavoidable manual step*.

## Decision

Implement three strategies behind one `ProvisioningStrategy` interface. The order records
which was used.

**A. Bot Pool** — operations pre-creates bots under platform-owned usernames; provisioning
assigns one and reconfigures it (`setMyName`, `setMyDescription`, `setMyCommands`,
`setWebhook`). Fully automatic, seconds, customer does nothing.
*Cost:* a generic `@username`.

**B. Guided Token Handoff** — a ~60-second guided BotFather flow; the customer pastes the
token once; we validate with `getMe`, encrypt it, take over the webhook, and never display it
again. *Cost:* one copy-paste. *Benefit:* the customer's own vanity username.

**C. Assisted MTProto** — an operations-only, feature-flagged tool that drives BotFather to
**refill the pool**. Never on a customer request path.

Sold as two tiers: **Instant** (A) and **Custom username** (B).

## Consequences

**Positive.** The promise is met in spirit — after the one-time handoff the customer never
sees a token, never configures a webhook, never manages infrastructure. Tier A is genuinely
zero-touch. ToS and ban risk are confined to an internal, flag-gated operations tool. The
interface means adding a real creation API later (if one ever appears) is a fourth
implementation, not a refactor.

**Negative.** Tier A cannot offer a custom username. Tier B has one manual customer step and
requires a ToS clause covering our storage and use of their token — legal review needed. The
pool requires operational stock management, monitoring and a low-watermark alert.

**Rejected: MTProto on the customer path.** A banned driving account would halt *all*
provisioning platform-wide, mid-order, for paying customers. Unacceptable single point of
failure for a marginal UX gain.

**Rejected: token handoff only.** Loses the "instant, zero-touch" product story entirely,
which is a large part of the value proposition.

## Open items

- [x] Product sign-off on the two tiers — **both A and B approved, 2026-08-11**.
- [ ] Pricing for the two tiers (`platform.telegram.instant` vs `platform.telegram.custom`
      price keys). Not blocking: the pricing engine is data-driven, so tiers can be priced
      after the code lands.
- [ ] **Legal review of the token-custody ToS clause.** Blocks *shipping* tier B to real
      customers, not building it. Tier A has no such dependency.
- [ ] Pool username scheme and initial depth, plus a low-watermark alert. Needed before
      tier A serves live orders; a default scheme is used for development.

## Implementation note (Phase 4)

`ProvisioningStrategy` has one method that matters — acquire a validated, encrypted
credential for a platform instance — with three implementations:

| Strategy | Acquisition | Customer step |
|---|---|---|
| `PoolAssignmentStrategy` | Claim an `AVAILABLE` `bot_pool_entry` under a row lock | None |
| `TokenHandoffStrategy` | Customer submits a token; validate via `getMe`, encrypt, discard the plaintext | One paste |
| `MtprotoRefillStrategy` | Ops-only pool refill, behind `PROVISIONING_MTPROTO_ENABLED` | Never on a customer path |

The order records `provisioning_strategy`, so a support agent can always answer "how did
this customer get their bot".

Tier B introduces a state the saga must handle that tier A does not: **waiting on the
customer**. A paid order can sit in `PROVISIONING` indefinitely because a human has not
pasted a token yet. That is a legitimate resting state, not a failure — the saga must not
time it out into `FAILED`, and the customer needs a reminder rather than an error.
