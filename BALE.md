# BALE INTEGRATION

Status: **Phase 0 — design + open questions** · Implemented in Phase 5 · Last updated: 2026-08-10

> **Read this first.** Bale exposes a Telegram-Bot-API-*shaped* HTTP API, and that
> resemblance is the single biggest trap in this project. It is a **different platform with a
> subset of methods and differing semantics**, not a drop-in. Implementing the Bale adapter
> as "Telegram with another base URL" will produce silent production failures in exactly the
> features customers paid for.
>
> **Phase 5 does not start until the capability spike in §2 is complete.** Everything marked
> ⚠️ below is unverified and must be confirmed against the live API, not assumed.

---

## 1. What we build on

- Base URL: `https://tapi.bale.ai/bot<token>/` (configured, never hard-coded).
- Bot creation: via Bale's own BotFather-equivalent in the Bale client. Like Telegram,
  **no programmatic creation** — the same three-strategy approach from
  [TELEGRAM.md](TELEGRAM.md) §2 applies (pool / guided handoff / ops-assisted).
- File API and update payloads are broadly Telegram-shaped ⚠️ but differ in detail.

## 2. Capability spike — the Phase 5 entry gate

A time-boxed spike against a real Bale test bot must answer each of these and record the
result here, with the raw responses committed as adapter test fixtures:

| # | Question | Impact if the answer is "no" |
|---|---|---|
| 1 | Does `setWebhook` exist, and does it support a secret token header? | Falls back to the sharded poller; ingress auth becomes HMAC + unguessable path |
| 2 | Are inline keyboards (`inline_keyboard` + `callback_query`) supported? | Every menu degrades to reply keyboards or numbered text |
| 3 | Max buttons per row / total; callback data size limit? | Menu layout rules for the adapter |
| 4 | `editMessageText` / `answerCallbackQuery` available? | No in-place menu updates; each step sends a new message |
| 5 | Max message length; parse modes supported? | Chunking and escaping rules |
| 6 | Media: photo, document, media groups; size limits? | Product images, receipts, catalogues |
| 7 | `setMyCommands` / `setMyName` / `setMyDescription`? | Provisioning must configure by hand or skip |
| 8 | Update payload field differences vs Telegram | Parser correctness |
| 9 | Rate limits (documented or empirical) | Gateway token-bucket configuration |
| 10 | Error response shapes and codes | Typed exception mapping, retry policy |
| 11 | Reachability from each candidate deployment region | Egress topology (see §4) |
| 12 | Deep-link `/start <payload>` support | Account linking for the Bale builder bot |

Until this table is filled in, **Bale-specific features must not be sold in the builder.**
`feature_platform_availability` is the switch that keeps that honest: a feature is offered on
Bale only when it is verified to work on Bale.

## 3. Adapter design

Same `PlatformAdapter` contract as Telegram. A conservative starting manifest, tightened or
loosened by the spike:

```python
Capabilities(
    inline_keyboards=???,        # ⚠️ spike Q2
    reply_keyboards=True,
    max_buttons_per_row=???,     # ⚠️ spike Q3
    media_groups=???,            # ⚠️ spike Q6
    message_editing=???,         # ⚠️ spike Q4
    web_app=False,
    max_text_length=???,         # ⚠️ spike Q5
)
```

The **degradation ladder** does the work wherever a capability is missing:

```
inline keyboard  → reply keyboard → numbered text menu ("1) …  2) …", user replies "2")
media group      → sequential sends
edit message     → send a new message
```

Core feature code is untouched by any of this — that is the whole reason for the adapter
layer (spec §4, rule 61.1). There is **no** `BaleAdapter(TelegramAdapter)` inheritance; both
implement the protocol independently and share only genuinely common helpers.

## 4. Egress topology (analysis R-03)

Telegram and Bale are generally not reachable from the same jurisdiction with equal
reliability. Bale traffic therefore runs on its own `worker-bale` Celery queue with its own
egress profile (`base_url`, `proxy_url`, timeouts, CA bundle), so it can be scheduled onto
different hosts or regions from Telegram traffic **with no code change**. Inbound Bale
webhooks terminate on a Bale-specific hostname. Per-platform reachability is probed and shown
on the admin System Health panel.

## 5. Multi-platform bots

A customer buying Telegram + Bale gets **two `bot_platform_instance` rows under one `bot`**,
sharing one `bot_configuration`, one business profile, one product catalogue, one appointment
calendar, one contact list. Business information is entered once (spec §3).

```
        Bot (tenant, template, configuration, business data)
         ├── BotPlatformInstance(telegram)  → credential, webhook, username
         └── BotPlatformInstance(bale)      → credential, webhook, username
```

An appointment booked through Bale is visible in the dashboard and can trigger a reminder on
either channel. Cross-channel end-user identity is *not* assumed: the same human on Telegram
and Bale is two `business_contact` rows unless they verifiably link (e.g. a matching verified
phone).

## 6. Bale Builder Bot (spec §46)

Functionally identical to the Telegram builder bot and a client of the same REST API — no
duplicated order logic. It can sell Telegram-only, Bale-only, or both. Account linking uses
the same single-use nonce deep-link mechanism, subject to spike Q12; if deep links are
unsupported, the fallback is a short code the user types into the bot.

## 7. Risks specific to Bale

- **Documentation drift** — Bale's API documentation is thinner than Telegram's, so behaviour
  must be pinned by recorded fixtures and a scheduled contract test that alerts when a
  response shape changes under us.
- **Silent divergence** — a method that exists but behaves differently is worse than one that
  is absent. The conformance suite asserts observable behaviour, not just HTTP 200.
- **Feature parity expectations** — the builder must clearly show which features are
  Telegram-only, so a customer never pays for something Bale cannot run.
- **Reachability** — treat egress as an operational dependency with its own alerting.

## 8. Open items

**Status after Phase 5 (2026-08-11): the code is built; the spike is not run.**

Everything that does not depend on the spike's answers is implemented and tested against
a fake transport: the Bale API client, the adapter and its parser, the provisioner, the
client registry, and the shared conformance suite. What is missing is *evidence*, and no
amount of code substitutes for it.

Bale therefore still ships `verified=False`. Concretely that means:

- The pre-payment preview tells customers the Bale layout is provisional.
- `feature_platform_availability` governs what may be sold on Bale, and a feature is only
  offered there once measured to work.
- Capabilities in `BALE_CAPABILITIES` are deliberately **conservative** — understating
  capability degrades presentation, overstating it sells a broken feature.

### How to close this

Create a Bale bot in the Bale app, then either:

```bash
python manage.py probe_bale --token <token> --chat <chat_id> --apply
```

or use **Django admin → Platform operations → Bale capability probe**, which does the
same thing from the browser and needs no shell access.

The probe answers the §2 table live — including binary-searching the real maximum message
length rather than trusting documentation — then writes the measured capabilities and
updates Bale feature availability.

- [ ] Run the §2 capability spike; paste the answers into §2 of this document.
- [ ] Paste the measured values into `BALE_CAPABILITIES` and set `verified=True`.
- [ ] Commit the probe output as adapter fixtures.
- [ ] Confirm the Bale bot-creation flow and the per-tier provisioning strategy.
- [ ] Confirm the deployment region / proxy for `worker-bale` — a probe that cannot reach
      Bale has answered Q11, not failed.
