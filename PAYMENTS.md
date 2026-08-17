# PAYMENTS, PRICING & CURRENCY

Status: **Phase 0 — design** · Last updated: 2026-08-10

MVP is manual payments only (spec §14–§16), but every manual flow runs through the same
provider abstraction a gateway will later plug into. Nothing in `orders` knows how money
arrives.

---

## 1. Money representation

```
Amount = (amount_minor: int, currency: str)
```

- Integer **minor units**. No floats anywhere, ever. No decimal without a currency.
- Per-currency exponent: `IRR 0`, `USD 2`, `EUR 2`, `USDT 6`, `BTC 8`.
- **Toman is not a currency.** It is IRR's display unit (`display_divisor = 10`). Storage,
  arithmetic and comparison are always in IRR minor units; the ÷10 happens in the formatter.
  Getting this wrong is a 10× billing error, so it is a schema-level decision, not a UI one.
- One order carries exactly one currency (spec §13). Mixed-currency orders are rejected at
  the domain layer.
- **No runtime FX conversion.** Each currency has its own admin-maintained price list. Prices
  therefore never drift with an exchange rate, and no customer can be quoted one number and
  charged another.
- Rounding, where unavoidable (percentage discounts), is banker's rounding on minor units,
  applied once at the line level, then summed — never applied to a total.

---

## 2. Pricing engine

Prices are **data**, and price history is **immutable**.

```
price_list (one per currency)
    └── price_version (immutable rows, valid_from … valid_to)
            price_key            amount_minor   billing_kind
            template.clinic.base      …         ONE_TIME
            platform.telegram.base    …         ONE_TIME
            platform.bale.base        …         ONE_TIME
            platform.multi.surcharge  …         ONE_TIME
            feature.appointment.setup …         ONE_TIME
            feature.ai.monthly        …         RECURRING_MONTHLY
            hosting.standard.monthly  …         RECURRING_MONTHLY
```

Changing a price **closes** the current version (`valid_to = now`) and **inserts** a new one.
There is no `UPDATE` and no `DELETE` on `price_version`, and the admin API exposes only
create-and-close. This is what makes spec §12's guarantee — *"if a feature costs $10 today
and $15 tomorrow, old orders must still show $10"* — true by construction rather than by
discipline.

### Multi-platform pricing (spec §9)

Shared work is billed once; only platform-specific work is additive:

```
total = template base
      + Σ platform base (per selected platform)
      + multi-platform surcharge   (only when >1 platform)
      + Σ feature price            (once, not per platform)
      + Σ platform-specific feature surcharge (only where one is configured)
      + hosting (recurring)
      − discounts
```

Two platforms therefore cost meaningfully less than 2 × one platform, which is both honest
and what the architecture actually costs us.

### Quote → Order

`build_quote()` resolves every applicable `price_key` to its **live** `price_version`, writes
`quote_item` rows referencing those version IDs, and stamps `expires_at` (default 24 h).
`place_order()` re-validates that the quote has not expired and copies each item into
`order_item` with **both** the `price_version_id` and the numeric values plus a full
`snapshot` JSONB. Even if the price list is later deleted outright, the order still renders
exactly as purchased.

The frontend never computes a total. It displays what `POST /quotes/{id}/price/` returned.

---

## 3. Payment provider abstraction

```python
class PaymentProvider(Protocol):
    slug: str
    kind: Literal["MANUAL_CARD", "MANUAL_CRYPTO", "GATEWAY"]

    def instructions(self, method, order, locale) -> PaymentInstructions: ...
    def accept_proof(self, payment, proof: ProofPayload) -> Payment: ...
    def verify(self, payment) -> VerificationResult: ...   # manual → PENDING_MANUAL_REVIEW
    def on_approved(self, payment) -> None: ...
```

```
PaymentProvider
├── ManualCardProvider     — Iranian card-to-card, receipt image
├── ManualCryptoProvider   — USDT/BTC/ETH, tx hash + optional screenshot
└── (future) GatewayProvider — Stripe, PayPal, Iranian gateways, crypto processors
```

A future gateway returns a real result from `verify()` instead of
`PENDING_MANUAL_REVIEW`, and implements a webhook handler. **No change is required in
`orders`.** That is the entire point of the abstraction.

---

## 4. Manual card payment (Iran)

Admin configures per method: card number, card holder, bank name, localized instructions,
minimum amount, country scope, enabled flag. Nothing is hard-coded (spec §14).

Customer flow:

```
Order total: ۴٬۹۰۰٬۰۰۰ تومان
Card:        XXXX-XXXX-XXXX-XXXX      [Copy]
Holder:      …
Bank:        …
[ Upload payment receipt ]
```

Receipt upload runs the full validation pipeline in [SECURITY.md](SECURITY.md) §7 —
private storage, MIME sniffing, size cap, image re-encode + EXIF strip, AV hook, SHA-256 and
perceptual hash indexed for duplicate detection. Then
`Payment → RECEIPT_SUBMITTED` and `Order → PAYMENT_REVIEW`.

> These are the **platform's** receiving card details. No customer card number, CVV or bank
> credential is ever collected or stored — that keeps the platform out of PCI scope entirely.

---

## 5. Manual crypto payment (international)

Admin manages wallets (spec §15) — never hard-coded:

```
name · currency · network · wallet_address · instructions · minimum_amount · enabled
```

e.g. `USDT/TRC20`, `USDT/ERC20`, `BTC/Bitcoin`, `ETH/Ethereum`.

Customer sees currency, network, address with a copy button, the exact amount, and submits:
`tx_hash` (optional but encouraged), `sender_wallet`, `network`, optional screenshot.

`tx_hash` has a **global unique constraint** — the same on-chain transaction cannot be
claimed against two orders.

Automatic on-chain verification is explicitly **out of scope for MVP**, but the seam is
ready: `ManualCryptoProvider.verify()` is the exact method a future
`ChainVerifyingCryptoProvider` overrides, using the already-stored `tx_hash`, `network` and
expected amount.

---

## 6. Payment state machine

```
PENDING ──► RECEIPT_SUBMITTED ──► UNDER_REVIEW ──┬──► APPROVED  → emits PaymentApproved → OrderPaid
                                                 └──► REJECTED  → order returns to PENDING_PAYMENT
```

Transitions are an explicit allow-list with a required actor role per edge. Approve/reject
are `FINANCE_AGENT`+, reject requires a reason, both are audit-logged with actor, IP and
before/after state, and the amount is re-validated server-side against the order at approval
time.

`PaymentApproved` is written to the **outbox** in the same transaction as the status change,
so the provisioning saga and the customer notification can never be lost — and can be
replayed if a worker dies.

---

## 7. Admin operations (spec §26)

Full CRUD on card methods and crypto wallets, enable/disable, edit instructions, review
queue with receipt preview via short-TTL signed URL, approve/reject with reason and internal
note, and filtering by currency, country, payment kind, status and date. Duplicate-hash and
duplicate-`tx_hash` matches are surfaced as review flags rather than silently blocked, so a
human decides.

---

## 8. Subscriptions (spec §50)

Orders can carry both one-time and recurring lines. Recurring lines create a `subscription`
on activation, with `current_period_end`, a grace window and manual admin renewal in v1:

```
ACTIVE ──(period end)──► GRACE_PERIOD ──(grace end)──► SUSPENDED
   ▲                                                       │
   └───────────── manual admin renewal / payment ──────────┘
```

`SUSPENDED` genuinely disables the runtime and removes the webhook — see
[BOT_RUNTIME.md](BOT_RUNTIME.md). An expiry that does not stop the bot is not an expiry.
