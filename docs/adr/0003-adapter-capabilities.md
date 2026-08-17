# ADR-0003 — Capability-negotiated platform adapters

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Bale's HTTP API is Telegram-Bot-API-*shaped*: same general method names, similar payloads,
different base URL. The tempting implementation is `class BaleAdapter(TelegramAdapter)` with
an overridden URL.

That is a trap. Bale supports a **subset** of methods with differing semantics (inline
keyboards, message editing, media groups, web apps, field names). Inheriting Telegram's
assumptions produces failures that appear only in production, in the paid features, for the
customers least able to diagnose them. Spec §59 also anticipates WhatsApp, Discord and a web
widget — none of which resemble Telegram at all.

## Decision

1. Every adapter implements a `PlatformAdapter` protocol independently. **No inheritance
   between adapters**; only genuinely shared helpers are factored out.
2. Each adapter publishes a `Capabilities` manifest (inline keyboards, max buttons per row,
   media groups, message editing, max text length, web app…).
3. The core emits abstract `Reply` objects — text keys, choices, attachments. It never emits
   a platform widget and never branches on platform.
4. Missing capabilities are handled by a fixed **degradation ladder** chosen by the adapter:
   `inline keyboard → reply keyboard → numbered text menu`, `media group → sequential sends`,
   `edit → new message`.
5. Feature availability per platform is **data** (`feature_platform_availability`), so the
   builder cannot sell a feature on a platform that cannot run it.
6. Every adapter passes the same `tests/conformance/` suite against recorded fixtures.
7. A third adapter, `preview`, renders to JSON for the pre-payment preview (spec §48) and
   doubles as the test double.

## Consequences

**Positive.** Business logic is written once (spec rule 61.1) and genuinely stays
platform-free — the `preview` adapter keeps proving it on every CI run rather than leaving it
as an aspiration. A new channel is a new package plus availability rows. Capability gaps
surface at build time in the catalogue instead of at runtime in a customer's bot.

**Negative.** More upfront abstraction than a single-platform product needs, and features
must be written against the lowest common denominator or explicitly declare a requirement.
Degradation output is less polished than hand-tuned platform UI. Both are accepted: the
alternative is duplicated business logic, which the specification forbids and which would be
far more expensive by Phase 7.
