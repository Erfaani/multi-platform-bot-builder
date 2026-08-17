# ADR-0004 — Money representation

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

The platform bills in IRR (displayed as Toman), USD, EUR and USDT. Currencies have different
exponents (IRR 0, USD 2, USDT 6, BTC 8). Iranian pricing is quoted in **Toman**, which is
IRR ÷ 10 — a unit, not a currency, and one with no ISO code.

Two failure modes are expensive and both are common:

1. Floating-point money → cents drift, totals that do not match the sum of their lines.
2. Treating Toman as a currency → a 10× billing error in either direction.

## Decision

1. Money is `(amount_minor: int, currency: str)`. **Floats are banned**, and a decimal
   without a currency is banned. Enforced by an `AmountField` composite so a developer
   cannot express money any other way.
2. Exponents live in the `currency` table, not in code.
3. **IRR is the currency; Toman is a display unit** (`display_divisor = 10`). Storage,
   arithmetic and comparison are always IRR minor units. The ÷10 happens only in the
   formatter.
4. One order carries exactly one currency; mixed-currency orders are rejected in the domain
   layer.
5. **No runtime FX conversion.** Each currency has its own admin-maintained price list.
6. Rounding is banker's rounding on minor units, applied once at the line level and then
   summed — never applied to a total.
7. Formatting exists in exactly one place per stack (`core.formatting`, `lib/format.ts`).

## Consequences

**Positive.** Exact arithmetic; totals always equal the sum of their lines. No exchange-rate
drift between quote and charge, so a customer can never be quoted one number and charged
another. Adding a currency is a row plus a formatting entry — no code change. The Toman trap
is closed structurally rather than by developer vigilance.

**Negative.** Prices must be maintained per currency by an admin rather than derived from one
base price via FX — more operational work, accepted deliberately in exchange for predictable
billing. `amount_minor` for IRR reaches large values, so `BIGINT` is required throughout.
