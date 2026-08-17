# ADR-0001 — Modular monolith over microservices

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

The platform spans ~20 domains (catalogue, pricing, orders, payments, provisioning, runtime,
several business modules, AI, analytics). It must scale to thousands of bots, but it starts
with no traffic and a small team. Spec §38 asks for a modular monolith; this ADR records why
that is right rather than merely instructed.

## Decision

One deployable Django project with hard internal boundaries:

- Layering `api → services → domain → models`, one direction only.
- Cross-app calls go through `services/` only; never another app's `api/` or internal
  `domain/` internals.
- The contract is machine-checked by `import-linter` in CI, so erosion fails the build
  instead of being noticed a year later.
- Async work is already split by queue (`default`, `telegram`, `bale`), which is where the
  real scaling pressure is.

## Consequences

**Positive.** One migration history, one transaction boundary — an order, its items and its
outbox message commit atomically, which is exactly what a payment system needs. No network
partition between pricing and orders. Local development is one `docker compose up`. The
enforced boundaries mean any app can be extracted later by replacing service calls with a
client, without touching callers.

**Negative.** All modules share a deployment cadence and a process failure domain. A runaway
query in analytics can affect API latency — mitigated by separate queues and, later, read
replicas. Team scaling eventually favours extraction; the boundaries are the preparation for
that day, not a commitment to it.

**Rejected: microservices from day one.** Distributed transactions across order/payment/
provisioning, N deployment pipelines and cross-service debugging, all before product-market
fit. The cost is immediate and the benefit is hypothetical.
