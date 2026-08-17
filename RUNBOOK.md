# RUNBOOK

Operator playbook for `ProvisioningJob` failures. Every code here is one of the 14
members of `PROVISIONING_ERROR_CODES` (`backend/apps/provisioning/saga.py`) — a closed,
enumerable set (`apps.provisioning.saga._normalize_error_code`) specifically so this
document can claim completeness: every code a job can carry has an entry below, and
`tests/test_runbook_completeness.py` fails the build if the two ever drift apart.

**General diagnosis, every code**: `/django-admin/provisioning/provisioningjob/` → find the
job (search by order number, tenant name, or the error code itself) → the detail page shows
`error_detail` (the real exception message) and the step-by-step trace (which step failed,
after how many attempts). Start there before assuming which of the entries below applies —
`error_code` narrows the category; `error_detail` has the specifics.

**General recovery**: a `FAILED` job with `is_resumable=True` shows **Retry** and **Release
pool entry** links directly in its admin row. Retry re-enters `run_job()` from the first
unfinished step — steps already `SUCCEEDED` are skipped, never replayed, so retrying is
always safe to attempt. Release (`compensate()`) returns any reserved pool entry to stock
without retrying — use it when the order itself needs to be cancelled or re-quoted instead.

---

## provisioning.pool_empty

**Fires when**: `PoolAssignmentStrategy.acquire()` (`apps/provisioning/strategies.py`) finds
no `BotPoolEntry` with `status=AVAILABLE` for the order's platform. The most common failure
in this list — pool depth is finite and orders are not.

**Customer impact**: order stuck in `FAILED`, customer sees a generic "processing" or
failure message depending on the frontend's polling state; no bot yet.

**Fix**:
1. Check current depth: `/django-admin/bots/botpoolentry/` filtered by platform and
   `AVAILABLE`, or `apps.bots.credentials.pool_depth(platform)` in a shell.
2. Restock: `/django-admin/bots/botplatforminstance/add-stock/` (`bots_pool_add`) — add one
   or more real bot tokens obtained from BotFather/Bale's bot creation flow.
3. Retry the job from its admin page. If several jobs failed for the same reason, retry
   each — there is no bulk-retry action by design (a bulk action failing partway is worse
   than seeing each result).

**Prevent recurrence**: this is exactly what `check_pool_depth` (scheduled every 30 min,
`apps.provisioning.tasks.CHECK_POOL_DEPTH_INTERVAL_SECONDS`) and the `botbuilder_bot_pool_depth`
Prometheus gauge are for — alert before the pool hits `settings.BOT_POOL_LOW_WATERMARK`,
not after the first order fails.

---

## provisioning.mtproto_disabled

**Fires when**: an order's strategy resolves to `"mtproto"` (Tier C) but
`settings.PROVISIONING_MTPROTO_ENABLED` is off.

**Customer impact**: same as `pool_empty` — order `FAILED`.

**Fix**: this tier is operations-only and feature-flagged for a reason (ADR-0002) — do not
simply flip the flag to unblock one order. Restock the pool instead (see
`provisioning.pool_empty`) and retry with the `pool` strategy. Only enable
`PROVISIONING_MTPROTO_ENABLED` as a deliberate, reviewed operations decision, never as an
incident reflex.

**Prevent recurrence**: N/A — this code firing means the flag is doing its job.

---

## provisioning.mtproto_not_on_customer_path

**Fires when**: something tried to run the MTProto strategy directly against a *customer*
order. `MtprotoRefillStrategy.acquire()` always raises this — the strategy exists solely to
refill the pool from operations tooling, never to serve an order (ADR-0002, rejected option:
a banned driving account would otherwise halt provisioning platform-wide mid-order).

**Customer impact**: order `FAILED`.

**Fix**: this indicates a bug in strategy selection (`apps.provisioning.strategies.strategy_for_order`),
not a capacity problem — retrying will fail identically. Re-run the job with `strategy="pool"`
or `"token_handoff"` instead (edit the job's `strategy` field is not exposed in admin by
design; re-create via `create_job(order=order, strategy="pool")` in a shell, or escalate to
engineering — this code should never occur in normal operation and is worth a bug report).

**Prevent recurrence**: if this recurs, the bug is in whatever assigns `strategy_for_order` —
file it, don't just keep manually re-routing orders around it.

---

## provisioning.unknown_strategy

**Fires when**: `get_strategy(slug)` is called with a slug not in `{"pool", "token_handoff",
"mtproto"}` — a data/config bug, e.g. a job's `strategy` field was hand-edited or a new
strategy was referenced before being registered in `_STRATEGIES`.

**Customer impact**: order `FAILED`.

**Fix**: check the job's `strategy` field in admin for a typo or stale value. If it is a
legitimately new strategy, the fix is code (`apps/provisioning/strategies.py`'s
`_STRATEGIES` dict), not an admin action — this is a deploy, not an incident response.

**Prevent recurrence**: this should be caught by tests before it ever reaches production;
treat a live occurrence as a test-coverage gap.

---

## provisioning.no_target_bot

**Fires when**: an add-on order's `order.target_bot` is `None` at `step_addon_bind_bot`
(`apps/provisioning/saga.py`) — an add-on (a customer buying more features for an existing
bot) must name which bot it applies to, and something let one through without that link.

**Customer impact**: the add-on purchase is stuck; the customer's *existing* bot is
unaffected (this step runs before anything touches it).

**Fix**: this is an order-creation bug, not something retrying fixes — the order needs
`target_bot` set correctly, which happens at checkout, not in this saga. Check how the order
was created (`apps.orders.services`) for how an add-on order can end up with no target bot;
likely needs the order re-created correctly rather than salvaged.

**Prevent recurrence**: add-on checkout should make `target_bot` a required, validated field
at order-creation time so this is caught before payment, not during provisioning.

---

## provisioning.no_bot

**Fires when**: `_require_bot()` needs `ctx.job.bot` for a later step (webhook setup,
smoke test, activation, ...) and no bot has been created yet — normally impossible in the
standard step order (`step_create_bot` always runs first), so this means an earlier step
was skipped, most often because a job's `strategy`/step list was altered after creation, or
a resumed job's step ordering was corrupted.

**Customer impact**: order `FAILED`.

**Fix**: inspect the job's step list in admin — confirm `create_bot` (or equivalent) shows
`SUCCEEDED`. If it does not, retry normally (the missing step will run). If it shows
`SUCCEEDED` but `job.bot` is still empty, this is a data-integrity bug — escalate to
engineering rather than retrying repeatedly, since retrying an inconsistent job is unlikely
to self-heal.

**Prevent recurrence**: treat any live occurrence as worth a root-cause investigation, not a
retry-and-move-on — the step order is meant to make this state unreachable.

---

## provisioning.smoke_test_failed

**Fires when**: `simulate_start()` (`apps/bot_runtime/dispatcher.py`'s synthetic `/start`,
run through the real dispatch pipeline with nothing actually sent) produces no reply text
for a platform the job just configured — the bot provisioned cleanly but cannot actually
answer, which must be caught by us, not the customer.

**Customer impact**: order `FAILED` — correctly so; shipping a bot that cannot reply would
be worse.

**Fix**: check which platform failed (`error_detail` names it) and reproduce
`simulate_start()` for that instance in a shell to see the actual rendered (or empty)
reply — this usually means a missing/misconfigured menu handler or a business template
whose default flow renders nothing for `/start`. Fix the underlying configuration or
template, then retry.

**Prevent recurrence**: this is the safety net for a bad business template or handler
config — if it fires for every bot on a given template, the template itself is broken and
should be pulled from sale until fixed, not treated as a one-off.

---

## bots.invalid_token

**Fires when**: `validate_token_shape()` rejects a token that does not match the
`<numeric id>:<chars>` shape Telegram/Bale tokens always have — reached from provisioning
via `read_pool_token`/`transfer_pool_credential` if a pool entry was somehow stocked with a
malformed token, or from a customer's token-handoff submission.

**Customer impact**: token-handoff orders show the customer an inline validation error
immediately (this rarely reaches a `ProvisioningJob` at all, since the API validates the
shape before accepting the submission) — as a *job* failure it almost always means a pool
entry, not a customer submission, was stocked incorrectly.

**Fix**: find the pool entry (`/django-admin/bots/botpoolentry/`) used by this job and check
its stored token was pasted correctly when added — if malformed, delete the bad entry and
add a corrected one (`bots_pool_add`), then retry.

**Prevent recurrence**: double-check tokens at stocking time; there is no server-side
recovery for a pool entry stocked with a typo'd token beyond replacing it.

---

## bots.token_already_registered

**Fires when**: `store_token()`'s fingerprint check finds the same token already bound to a
*different* instance — reached during provisioning via `transfer_pool_credential` if a pool
entry's token was already claimed elsewhere (a stocking race or duplicate stock entry).

**Customer impact**: order `FAILED`.

**Fix**: find which instance already holds that fingerprint
(`/django-admin/bots/botcredential/`, search is by fingerprint, not raw token — the token
itself is never queryable, by design, SECURITY.md §5) and confirm whether that binding is
legitimate. If the pool entry was a duplicate of an already-issued bot, delete the pool
entry (do not delete the credential of a live bot) and restock with a genuinely new token,
then retry.

**Prevent recurrence**: this is the system correctly refusing to let two customers end up
on the same bot — never "fix" it by force-reassigning the existing credential.

---

## order.illegal_transition

**Fires when**: the saga tries to move the order to a status the state machine does not
allow from its current one (`apps.orders.domain.state_machine.check` raising
`IllegalTransition`) — almost always means the order's status was changed by something
outside the saga (a manual admin edit, a duplicate event) between when the job started and
when this step ran.

**Customer impact**: order `FAILED`, and its status is whatever it was left at — check it
directly, it may not need "fixing" so much as understanding.

**Fix**: read the order's status and audit log (`apps.audit`) to see what actually happened
to it. If the order is already further along than this job expected (e.g. already `ACTIVE`
from a duplicate `order.paid` event racing this job — at-least-once delivery makes this
possible), the job is likely stale and does not need retrying at all. If the order was
genuinely corrupted by a manual edit, that edit needs to be understood and reverted before
retrying will make sense.

**Prevent recurrence**: N/A — this is the state machine correctly refusing to make things
worse; investigate the *order's* history, not this job in isolation.

---

## order.transition_forbidden

**Fires when**: the transition is *legal* for the state machine but not for this actor —
`check()` raising `TransitionNotPermitted`, e.g. missing scopes. Inside the saga this points
at a bug (the saga always transitions as `Actor.SYSTEM`, which should hold every scope this
path needs) rather than an operator permissions problem.

**Customer impact**: order `FAILED`.

**Fix**: this should not happen from the saga's own automatic transitions — if it does,
capture the full `error_detail` and escalate to engineering rather than retrying repeatedly;
retrying will not change which actor the saga transitions as.

**Prevent recurrence**: treat as a bug report, not an operations task.

---

## provisioning.credential_error

**Fires when**: `apps.bots.credentials.CredentialError` — a stored credential could not be
decrypted (`decrypt()` failing in `read_pool_token`/`read_token`). Common causes: the
`ENCRYPTION_KEK` changed without a proper key-rotation migration, or the ciphertext's
associated-data binding (`instance:{public_id}`) no longer matches because the row was
copied or reassigned to a different instance.

**Customer impact**: order `FAILED`; for an *existing* live bot this same error surfaces
outside provisioning too (sends fail) — check whether this is isolated to one job or
systemic across many bots, which changes the urgency enormously.

**Fix**: if isolated to one credential row, the token is unrecoverable — the customer or
operations must supply it again (token-handoff) or the pool entry must be replaced
(restock). If systemic across many bots at once, **stop** — this points at a KEK problem,
not a per-bot data issue; do not attempt per-job fixes, escalate immediately per
SECURITY.md's key-rotation procedure.

**Prevent recurrence**: this is exactly why `SECURITY.md` treats `ENCRYPTION_KEK` rotation
as a deliberate, tested procedure rather than a plain environment-variable edit.

---

## provisioning.platform_api_error

**Fires when**: `apps.platforms.transport.PlatformApiError` escapes a step — Telegram/Bale's
API rejected or failed a call the saga made (`setWebhook`, `setMyCommands`, `getMe`, ...)
in a way not otherwise absorbed as a normal outcome.

**Customer impact**: order `FAILED`, but often transient — many platform API errors are the
platform itself having a bad moment, not a permanent problem with this order.

**Fix**: check `error_detail` for the platform's actual error message and HTTP status.
- A transient/5xx-shaped error from the platform: just retry — it will very likely succeed.
- A 401/403-shaped error: the pool entry's token was likely revoked on the platform side
  (someone deleted the bot via BotFather, or it was banned) — the token is dead regardless
  of retrying; remove the pool entry/credential and treat it like a bad token
  (`bots.invalid_token`/`bots.token_already_registered` remediation) rather than retrying.
- A sustained spike across many jobs at once on one platform: that platform is likely down;
  stop retrying individual jobs and wait — check the platform's own status page.

**Prevent recurrence**: N/A — this is an external dependency; the saga already retries
resumably rather than replaying completed steps, which is the main mitigation available.

---

## provisioning.unexpected_error

**Fires when**: `_normalize_error_code` (`apps/provisioning/saga.py`) hits any exception
that is not an `AppError`, `CredentialError`, or `PlatformApiError` — a genuine bug
somewhere in a step handler. This code exists specifically so an unenumerable Python
exception class name is never leaked into `error_code` (Phase 10) — it is the deliberate
catch-all, not a sign the classification is incomplete.

**Customer impact**: order `FAILED`.

**Fix**: `error_detail` carries `f"{type(exc).__name__}: {exc}"`, and the full traceback is
in the worker's structured JSON logs (search by the job's `request_id`, propagated from web
request through to the worker task — Phase 10). This is always worth a bug report; retrying
blind is a coin flip depending on whether the underlying bug is data-dependent or not.

**Prevent recurrence**: every occurrence of this code should end in either a code fix or a
new, more specific entry in `PROVISIONING_ERROR_CODES` for whatever it turned out to be —
this code should describe a rare edge, not become a dumping ground.

---

## Completeness

`tests/test_runbook_completeness.py` parses this file's `## <code>` headings and asserts the
set matches `apps.provisioning.saga.PROVISIONING_ERROR_CODES` exactly — a new failure code
added to the saga without a matching runbook entry fails the test suite, not just this
document going stale silently.
