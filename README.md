# Bot Builder Platform

A multi-tenant **Bot-as-a-Service** platform. Customers configure and buy a business bot for
**Telegram** and/or **Bale**; the platform provisions, hosts, configures and runs it. The
customer never touches a server, a webhook, a container or a line of code.

> **Status: all 10 phases complete** — backend, frontend, and production hardening
> (structured logging, PostgreSQL row-level security, metrics, backup/restore drill, load
> testing, runbooks). See [PHASES.md](PHASES.md) for the phase-by-phase history and
> [DEPLOYMENT.md](DEPLOYMENT.md) for current operational status.

---

## The idea in one picture

```
   Website · Telegram builder bot · Bale builder bot
                        │
                 same REST API
                        ▼
   Quote → Order → Manual payment → Admin approval
                        ▼
              Provisioning saga (async)
                        ▼
        ┌───────────────┴───────────────┐
   Telegram bot                     Bale bot
        └───────────────┬───────────────┘
                        ▼
          One shared core · one configuration
             one business database
```

A customer purchase creates **rows, not a codebase**. One engine, thousands of bots.

## Documentation

Read in this order:

| Document | What it answers |
|---|---|
| [docs/00-ANALYSIS.md](docs/00-ANALYSIS.md) | **Start here.** What the spec gets wrong, and the decisions taken instead |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layering, app boundaries, adapters, feature manifests |
| [DATABASE.md](DATABASE.md) | ERD, tables, constraints, indexing |
| [API.md](API.md) | Endpoint contract, error format, conventions |
| [SECURITY.md](SECURITY.md) | Tenancy isolation, credential handling, uploads, audit |
| [I18N.md](I18N.md) | fa/en, RTL, Jalali dates, Toman vs IRR |
| [PAYMENTS.md](PAYMENTS.md) | Money representation, pricing engine, manual card & crypto |
| [BOT_RUNTIME.md](BOT_RUNTIME.md) | Webhook ingress, dispatch, sessions, outbound gateway |
| [TELEGRAM.md](TELEGRAM.md) | Telegram limits and the provisioning problem |
| [BALE.md](BALE.md) | Bale differences and the required capability spike |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Services, topology, migrations, backups |
| [PHASES.md](PHASES.md) | Phase plan and dependency graph |

## Four decisions worth knowing up front

1. **Bots cannot be created via API.** Neither Telegram nor Bale offers it. Provisioning uses
   a pre-created **bot pool** (instant, generic username) or a **guided token handoff**
   (customer's own username, token surrendered once and never shown again).
   → [docs/00-ANALYSIS.md](docs/00-ANALYSIS.md) R-01
2. **Bale is not Telegram.** Adapters negotiate capabilities and degrade explicitly; there is
   no shared inheritance and no assumed parity. → [BALE.md](BALE.md)
3. **Prices are immutable versions.** Changing a price closes a row and inserts a new one, so
   a two-year-old order still renders exactly as purchased. → [PAYMENTS.md](PAYMENTS.md) §2
4. **Money is integer minor units + currency.** Toman is a *display unit* of IRR, not a
   currency — mishandling that is a 10× billing error. → [I18N.md](I18N.md) §4

## Stack

Python 3.12 · Django 5.2 LTS · DRF · PostgreSQL 16 + pgvector · Redis 7 · Celery 5 ·
Next.js 15 · TypeScript · Tailwind · Docker

## Getting started

Phase 1 is complete and runnable.

```bash
cp .env.example .env      # fill in every CHANGE_ME
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_demo --demo
docker compose exec backend python manage.py createsuperuser
```

Backend `:8000` (`/api/v1/docs/`) · Frontend `:3000` · Nginx `:8080`.
Webhooks need a public HTTPS tunnel; without one set `BOT_RUNTIME_MODE=polling`.

`seed_demo --demo` creates `admin@example.com` and `owner@example.com` with the password
`ChangeMe!2026`. **Local development only** — the command prints a warning to that effect.

### Running the backend outside Docker

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements/local.txt
docker compose up -d postgres redis
cd backend && python manage.py migrate && python manage.py runserver
```

Tests need a PostgreSQL to point at:

```bash
TEST_DATABASE_URL=postgres://botbuilder:<password>@localhost:5432/botbuilder \
  python -m pytest tests
```

### If ports are already taken

`POSTGRES_HOST_PORT` and `REDIS_HOST_PORT` in `.env` set the host ports the containers
publish. A PostgreSQL installed natively on the machine will otherwise **shadow the
container** and surface as a confusing `password authentication failed` — the container is
running fine, you are simply talking to a different server. Same idea for a stray Node app
on `:3000`.

On Windows, write `.env` without a BOM. django-environ rejects a BOM'd first line
(`Invalid line: ﻿#`); PowerShell's `Set-Content -Encoding utf8` adds one.

## Repository layout

```
backend/
  config/            Django project: split settings, urls, celery
  apps/
    core/            base models, money, encryption, outbox, errors
    accounts/        users, auth, staff RBAC
    customers/       tenants, memberships, roles
    businesses/      business profiles, hours, branding
    business_templates/  clinic, restaurant, shop, …
    features/        feature catalogue + manifests
    pricing/         price lists, immutable price versions, quote engine
    orders/          quotes, orders, state machine
    payments/        methods, payments, receipts, providers
    bots/            bots, platform instances, credentials, configuration
    provisioning/    saga, strategies, bot pool
    bot_runtime/     webhook ingress, dispatch, sessions, outbound gateway
    platforms/       adapter registry + telegram/ bale/ preview/
    appointments/ commerce/ crm/            business modules
    notifications/ analytics/ support/ subscriptions/ ai/ audit/ i18n_content/
  requirements/  locale/  tests/
frontend/            Next.js app
docker/              Dockerfiles, nginx, postgres init
docs/                analysis + ADRs
```

## Development rules

The non-negotiables from the specification, restated because they are easy to erode:

no duplicated business logic between Telegram and Bale · no hard-coded prices · no
hard-coded customer configuration · no bot token in any response, log or serializer · no
secrets in source · no trusting frontend authorization · no business logic in views or
serializers · adapters isolated · payment providers abstract · translations externalized ·
background jobs idempotent and retryable · tests on critical flows · the system stays
runnable after every phase.
