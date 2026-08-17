# DEPLOYMENT

Status: **Phase 10 — production hardening complete** · Last updated: 2026-08-17

---

## 1. Services

| Service | Role | Scaling |
|---|---|---|
| `nginx` | TLS termination, static/media proxy, routing | 1+ |
| `backend` | Django + DRF (gunicorn/uvicorn), stateless | horizontal |
| `frontend` | Next.js | horizontal |
| `worker-default` | Celery: notifications, analytics, files, AI | horizontal |
| `worker-telegram` | Celery: Telegram dispatch, sends, provisioning | horizontal, own egress |
| `worker-bale` | Celery: Bale dispatch, sends, provisioning | horizontal, own egress |
| `beat` | Celery scheduler (reminders, subscriptions, rollups) | **exactly 1** |
| `postgres` | PostgreSQL 16 + pgvector | managed in prod |
| `redis` | Broker, cache, sessions, rate-limit buckets | managed in prod |

`worker-telegram` and `worker-bale` are separate services specifically so they can be
scheduled onto hosts with different network egress (analysis R-03). In a single-region
deployment they are just two queues.

```
                          Internet
                             │
                    ┌────────▼────────┐
                    │      Nginx      │  TLS, HSTS, rate limit, body caps
                    └───┬─────────┬───┘
        /api/* /webhooks/*        │  everything else
                        │         │
                 ┌──────▼───┐  ┌──▼────────┐
                 │ backend  │  │ frontend  │
                 └──┬────┬──┘  └───────────┘
                    │    │
        ┌───────────▼┐  ┌▼────────┐
        │ postgres   │  │  redis  │
        └────────────┘  └──┬──────┘
                           │
        ┌──────────────────┼──────────────────┬──────────┐
        ▼                  ▼                  ▼          ▼
  worker-default   worker-telegram      worker-bale     beat
```

## 2. Local development

```bash
cp .env.example .env          # then fill in the values marked CHANGE_ME
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_demo
docker compose exec backend python manage.py createsuperuser
```

- Backend `http://localhost:8000` · API docs `/api/v1/docs/` · admin `/django-admin/`
- Frontend `http://localhost:3000`

**Webhooks in development.** Platforms require a public HTTPS URL, so use a tunnel
(`cloudflared` / `ngrok`) and set `PUBLIC_WEBHOOK_BASE_URL` to the tunnel hostname. Without a
tunnel, set `BOT_RUNTIME_MODE=polling` to use the sharded development poller instead.

## 3. Configuration

Everything is environment-driven ([.env.example](.env.example)); no secret is ever committed.
Settings are split: `config/settings/{base,local,production,test}.py`, selected by
`DJANGO_SETTINGS_MODULE`. Production asserts on boot that `DEBUG` is false, `SECRET_KEY` and
`ENCRYPTION_KEK` are not defaults, `ALLOWED_HOSTS` is set, and TLS-related flags are on —
the process refuses to start otherwise, so a misconfigured deploy fails loudly instead of
running insecurely.

## 4. Migrations

`python manage.py migrate` runs as a release step **before** new application containers take
traffic. Rules: additive changes first, deploy, then destructive changes in a later release
(expand/contract); no destructive migration in the same release as the code that stops using
the column; every migration reviewed for table locks on large tables
(`inbound_update`, `analytics_event` are partitioned and must use concurrent index creation).

## 5. Production notes

- Run `backend` behind gunicorn with `--workers 2×CPU+1`, `--timeout 30`; long work belongs
  in Celery, never in a request.
- Nginx: `client_max_body_size` sized to the largest upload (20 MB), separate stricter limits
  on `/webhooks/`, and security headers per [SECURITY.md](SECURITY.md) §9. Keep `/metrics`
  off the public edge (internal network / IP allowlist only) — it isn't authenticated at the
  app layer, the same posture as `/healthz`/`/readyz`.
- Static files via WhiteNoise or CDN; **user media is never served by nginx** — it lives in
  private object storage behind signed URLs.
- `beat` must be a single replica, or reminders fire twice. As of Phase 10, `CELERY_BEAT_SCHEDULE`
  (`config/settings/base.py`) also carries the sweep/DLQ safety-net tasks below — these
  existed as code since earlier phases but were never actually scheduled anywhere, so none
  of them had ever run outside a test or a manual shell call before this phase:
  - `sweep-outbox` (5 min) — outbox messages whose `on_commit` publish never fired.
  - `purge-idempotency-records` (6 h) — expired `Idempotency-Key` rows.
  - `check-bot-pool-depth` (30 min) — also updates the `botbuilder_bot_pool_depth` gauge.
  - `sweep-inbound-updates` (2 min) — inbound updates whose enqueue failed at ingress.
  - `outbound-retry` (1 min) — **the only thing that ever retries a rate-limited outbound
    message.** Without this entry a message deferred by rate limiting stayed `QUEUED`
    forever in any real deployment; this was the sharpest gap found in the Phase 10 audit.
  - `purge-sessions` (6 h) — expired bot conversation sessions.
- Celery: `acks_late=True`, `prefetch_multiplier=1`, per-queue concurrency,
  `worker_hijack_root_logger=False` (`config/celery_app.py` — Celery's default silently
  discards Django's JSON logging/request-id/secret-redaction for worker processes
  otherwise). Job retry/DLQ policy (Phase 10):
  - Tasks whose failures are already fully absorbed into a domain status field
    (`provision_order` → `ProvisioningJob.error_code`, staff-retried via the admin's
    **Retry** button; `deliver_notification`'s email path → `DeliveryStatus.FAILED`)
    declare no Celery-level retry — one was never real, since nothing inside them ever
    called `self.retry()`. `scan_receipt` is presently a stub with nothing that can fail.
  - `process_update` and `deliver_notification` declare a narrow `autoretry_for` scoped to
    genuine transient infra exceptions only (`OperationalError`, and for `process_update`
    also `django_redis.exceptions.ConnectionInterrupted` for the Redis-backed session
    store) — a real bug in a handler still surfaces immediately instead of being retried
    into silence.
  - `FailedTaskLog` (`apps.core.models`, admin-visible, read-only) is the cross-cutting
    DLQ: populated by the `task_failure` Celery signal
    (`apps.core.celery_signals._log_task_failure`), which only fires once a task is done
    retrying — one row per genuine terminal failure, not per attempt — independent of
    whatever domain-specific tracking that task already has for itself.
- Zero-downtime: rolling replacement, health-checked, with `/healthz` (liveness — never
  touches the database, by design) and `/readyz` (DB + cache + migrations current).

## 6. Backups & recovery

Nightly PostgreSQL base backup plus continuous WAL archiving; object storage versioned with
lifecycle rules. Redis is treated as disposable: nothing is stored only there. Targets: RPO
15 min, RTO 2 h — the WAL-archiving cadence and nightly schedule that make those targets
real are a deployment-infra setup step, not yet wired up anywhere but locally in dev.

`scripts/backup.sh` / `scripts/restore.sh` (`pg_dump -F c` / `pg_restore`, via `docker
compose exec postgres`) are the mechanism; `restore.sh` targets a separate database by
default (`botbuilder_restore_drill`), never the live one, so it is always safe to run
against a production dump.

**Restore drill run 2026-08-17**, against the dev Postgres 16 container: `backup.sh`
produced a 456 KB custom-format dump; `restore.sh` restored it into a fresh
`botbuilder_restore_drill` database. Verified, not assumed: table count matched (83/83),
row counts matched exactly on spot-checked tables (`django_migrations` 61, `currency` 4),
and — the part that actually matters for this platform — **RLS survived the round trip**:
26/26 tables still had `relrowsecurity` set and their `tenant_isolation` policy present
after restore. The drill database was dropped immediately after verification; it is not a
standing fixture.

## 7. Observability

Structured JSON logs (`apps.core.logging`, `structlog` + a `ProcessorFormatter` so both
`structlog.get_logger()` and the plain `logging.getLogger(...)` calls used almost
everywhere converge on one pipeline) with `request_id` propagated from the API through
Celery (`apps.core.celery_signals`, via message headers — `worker_hijack_root_logger=False`
is what actually lets it reach worker log output, found only by testing a live round trip,
not by reading the code); error tracking via Sentry with release tagging
(`config/settings/production.py`).

**Metrics** (`django-prometheus` + `apps.core.metrics`, scraped at `/metrics`):
request latency and count by view/method (free from `django-prometheus`'s middleware —
this also covers webhook ingress latency, since the webhook view is a normal Django view);
`botbuilder_outbound_send_total{outcome}` (sent / rate_limited / dropped / retrying /
failed — "outbound send success rate and 429 rate"); `botbuilder_provisioning_job_total{status,error_code}`
("provisioning success/failure by `error_code`" — `error_code` is safe to use as a label
because `PROVISIONING_ERROR_CODES` is a closed, enumerable set, not free text);
`botbuilder_bot_pool_depth{platform}` (updated by the newly-scheduled `check-bot-pool-depth`
task); `botbuilder_celery_queue_depth{queue}` (a live `LLEN` against the Redis broker at
scrape time, not a counter — queue depth is current state, not a counted event).

**PostgreSQL Row-Level Security** (`apps/core/migrations/0002_row_level_security.py`,
`apps.core.tenant_session`): the app's own DB user is the tables' owner (needed for
migrations), and RLS is unconditionally bypassed for a superuser or table owner — so RLS
alone on that connection would be pure theater. A second, deliberately unprivileged role
(`botbuilder_app`, `NOLOGIN NOSUPERUSER NOBYPASSRLS`) is what every serving connection
actually runs as, via `SET ROLE` on `connection_created` — set once, for that physical
connection's entire lifetime, deliberately never reset per-request (a pooled connection
under `CONN_MAX_AGE` never fires `connection_created` again; a bug during Phase 10 development
that briefly re-ran `RESET ROLE` on every request would have silently restored full
owner privileges — i.e. silently disabled RLS — for every request after a pooled
connection's first one; caught live, not by reading the code, and now has a permanent
regression test, `tests/test_tenant_session.py`). Set `DATABASE_APP_ROLE=botbuilder_app` to
enable the drop in a given environment — empty (the local/test default) keeps RLS policies
present but unenforced, exactly as Postgres always treats a table owner.

**Alerts** (not yet wired to a paging system — the metrics and log fields below exist for
this, wiring them to an alerting backend is not yet done): failed provisioning jobs
(`botbuilder_provisioning_job_total{status="failed"}` by `error_code` — see
[RUNBOOK.md](RUNBOOK.md) for the response to each one), queue lag
(`botbuilder_celery_queue_depth`), pool depth low (`botbuilder_bot_pool_depth` under
`BOT_POOL_LOW_WATERMARK`; `check_pool_depth` already logs a warning at this threshold),
platform unreachable (`botbuilder_outbound_send_total{outcome="failed"}` spike), payment
review backlog, error-rate spike (`botbuilder_outbound_send_total{outcome="rate_limited"}`
or Sentry's own rate).

## 8. Load testing

**Target** (docs/00-ANALYSIS.md R-04, at the doc's 1,000-bot reference scale): webhook
ingress — receive, validate, persist `InboundUpdate`, enqueue — p99 under 50 ms.
`scripts/load_test_webhook.py` measures exactly this: HTTP response latency for
`POST /webhooks/telegram/<instance>/` against a real running server and a real Redis
broker (not `CELERY_TASK_ALWAYS_EAGER`, which would measure full synchronous message
processing instead of the ingress-and-enqueue path the target is actually about).

**Run 2026-08-17**, dev hardware (a single developer laptop — Windows, one dev Postgres 16
container with no connection pooler in front of it, `waitress` in place of gunicorn since
gunicorn does not run on Windows at all). Reported honestly as such, not as a production
SLO proof — production's PgBouncer/connection pooling and warm long-running gunicorn
workers are exactly the difference this number cannot speak to:

| Concurrency | p50 | p95 | p99 | Result |
|---|---|---|---|---|
| 10 | 29.7 ms | 39.2 ms | 48.5 ms | **meets the 50 ms target** |
| 20 | 53.7 ms | 84.7 ms | 122.8 ms | over target |
| 40 | 120.7 ms | 434.7 ms | 780.7 ms | over target, non-linear degradation |

The degradation past concurrency 20 traces to Postgres backend-process-per-connection
cost on a single, unpooled dev instance (confirmed directly: sequential warmed requests on
the same connection ran 23–47 ms regardless of load; a burst of fresh concurrent connections
is what got slow, and at concurrency 100 a *default* `pgvector/pg16` image's
`max_connections=100` was hit outright, surfacing as `FATAL: sorry, too many clients
already`). Production's connection pooling exists specifically to remove this variable —
this measurement is best read as "the application logic itself is fast enough to hit the
target (concurrency-10 result); production capacity planning needs PgBouncer sized for the
real concurrent-connection count at target bot volume, not a bigger `max_connections`."

## 9. Environments

`local` (compose) → `staging` (production-shaped, separate bot pool and test bots, seeded
demo tenant) → `production`. Distinct secrets and distinct KEKs per environment; no
production secret ever exists on a developer machine.
