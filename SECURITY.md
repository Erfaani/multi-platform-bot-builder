# SECURITY

Status: **Phase 0 — model** · Last updated: 2026-08-10

The two assets that matter most: **bot credentials** (a leak hands an attacker a customer's
live business channel) and **tenant data isolation** (a leak exposes one business's patients
or customers to another). Everything below is ordered around those.

---

## 1. Trust boundaries

```
 untrusted ─── browser / builder bots ───► API (authn + authz + tenancy)
 untrusted ─── platform webhooks ────────► ingress (per-bot secret, no logic)
 untrusted ─── uploaded files ───────────► private storage (validated, never executed)
 trusted ───── admin panel ──────────────► staff RBAC + audit + step-up for money actions
 secret ────── KEK / tokens / DB creds ──► env or KMS, never in source, never in responses
```

---

## 2. Authentication

- Argon2id password hashing (Django default backend replaced), minimum length 12,
  breach-list check on registration and reset.
- JWT: access 15 min, refresh 14 days, **rotating with blacklist on use**. Refresh tokens
  are single-use; reuse of a rotated token invalidates the whole family (detects theft).
- Django admin uses sessions with `Secure`, `HttpOnly`, `SameSite=Lax`, and a short idle
  timeout.
- Throttles: login 10/min per IP *and* per account, password reset 5/hour, registration
  20/hour per IP. Generic failure messages — never "no such user".
- Email verification required before an order can be placed.
- Extensible to phone OTP / Telegram Login / social via `accounts.services.issue_tokens()`;
  Telegram Login payloads must be verified by HMAC against the bot token, with `auth_date`
  freshness checked.

## 3. Authorization

Two independent RBAC systems:

- **Tenant roles** — `OWNER` (everything incl. billing and members), `MANAGER` (bots,
  business data, no billing/members), `STAFF` (scoped operational data only, e.g. a clinic
  receptionist sees appointments but not orders).
- **Staff roles** — `SUPER_ADMIN`, `ADMIN`, `SUPPORT_AGENT`, `FINANCE_AGENT`,
  `BOT_OPS_AGENT`. Least privilege: support cannot approve payments; finance cannot
  suspend bots; nobody but super-admin reads audit logs.

Every endpoint declares required permissions explicitly. There is no implicit "authenticated
means allowed".

## 4. Multi-tenant isolation — the highest-risk control

Four layers, because any single one will eventually be forgotten:

1. `TenantOwnedModel`: non-null `tenant` FK, composite indexes leading with `tenant_id`.
2. Tenant-scoped manager — retrieving unscoped data requires an explicit, greppable
   `.unscoped()` call.
3. `TenantScopedViewSet` derives the tenant from the **authenticated principal only**.
   A `tenant_id` in a request body or query string is ignored, always.
4. Object-level permission check on every detail route; cross-tenant access returns **404**,
   never 403 (a 403 confirms existence).

**Automated proof.** `tests/security/test_cross_tenant.py` enumerates every route in the DRF
router, creates tenants A and B with a full object graph, and asserts that B's token gets 404
on all of A's `public_id`s across GET/PATCH/DELETE. A new endpoint is covered the moment it
is registered — there is nothing to remember.

Phase 10 adds PostgreSQL RLS with a per-request `SET LOCAL app.tenant_id`, so even a raw SQL
mistake cannot cross tenants.

## 5. Bot credentials

- **Envelope encryption**: random DEK per credential (AES-256-GCM), DEK wrapped by a KEK
  from `ENCRYPTION_KEK` (env) or KMS. Stored with `kek_version` so keys can be rotated
  without downtime.
- A `fingerprint` (HMAC of the token) allows duplicate/equality checks without decryption.
- Decryption happens **only** inside `platforms/` transport code, only in worker processes,
  and the plaintext never leaves the function scope.
- **No serializer, no admin view, no API route, no log line ever contains a token.** A
  logging filter redacts anything matching bot-token shape; `tests/security/test_no_secret_leak.py`
  crawls every API response and asserts no match.
- Rotation: re-encrypt on KEK bump via a management command; webhook secrets rotate with an
  overlap window (old and new accepted simultaneously).

## 6. Webhook ingress

- Unguessable `bot_public_id` (UUIDv4) in the path.
- Per-bot secret: Telegram's `X-Telegram-Bot-Api-Secret-Token` where supported; otherwise
  HMAC-SHA256 over the raw body in a header. **Constant-time comparison.**
- Optional source-IP allowlist per platform, when the platform publishes stable ranges.
- Replay protection via unique `(bot_platform_instance_id, platform_update_id)`.
- Body size cap; JSON depth cap; the view performs no external calls and holds no locks.
- Suspended or archived bots reject updates *before* any processing.

## 7. File uploads

Applies to receipts, logos, AI documents, support attachments — **and**, since Phase
10.5, product/property/course photos, which are the one deliberate exception to the
"private" rule below.

- Private bucket by default. `MEDIA_URL` serves nothing user-uploaded.
  - **Exception**: product/property/course photos (`apps.commerce.models.ProductImage`
    / `PropertyImage` / `CourseOffering.thumbnail`) are stored under a `public/` prefix
    and are meant to be shown to end customers browsing a bot — a signed URL would be
    the wrong tool for content that is supposed to be publicly linkable. Everything else
    in this list still applies to them unchanged (allowlist, size cap, re-encoding,
    filename regeneration, SVG rejection); only the delivery mechanism differs. Nothing
    outside that one prefix is ever served — see `config/urls.py` and
    `apps.commerce.models._public_upload_to`.
- Everything *not* under `public/` (receipts, logos, AI documents, support attachments):
  access via short-TTL (5 min) signed URLs; every issuance is audit-logged with the actor.
- Extension **and** content-sniffed MIME must both be on the allowlist
  (`image/jpeg`, `image/png`, `image/webp`, `application/pdf`).
- Size caps (receipts 5 MB, logos 2 MB, documents 20 MB, public photos 5 MB).
- Images are re-encoded server-side, stripping EXIF (GPS in a receipt photo is a privacy
  problem) and any embedded payload.
- Filenames are regenerated; the original is stored as metadata only. No path traversal
  surface.
- `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` on delivery of
  private uploads.
- AV scan hook before an admin can open a private file.
- SVG is **rejected** everywhere — it is an XSS vector.

## 8. Payments integrity

- `tx_hash` carries a global unique constraint — one blockchain payment cannot settle two
  orders.
- Receipt `sha256` (and perceptual hash) is indexed; reuse across orders raises a review flag.
- Approve/reject are `FINANCE_AGENT`+ only, require a reason on reject, and are audit-logged
  with actor, IP and before/after state.
- Amounts are re-validated server-side against the order at approval time; a client-supplied
  amount is never trusted.
- Payment status transitions use the same allow-list mechanism as orders.

## 9. Web hardening

CSRF on all session-authenticated routes · CORS allowlist by exact origin (no wildcard with
credentials) · HSTS, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy` · strict CSP on the admin (this is where untrusted receipts are viewed) ·
ORM only, no string-interpolated SQL · React auto-escaping, `dangerouslySetInnerHTML` banned
by lint · all customer-supplied content escaped before it reaches a bot message.

## 10. Rate limiting & abuse

Per-IP and per-account API throttles · per-bot and per-chat outbound token buckets (also
protects us from platform bans) · builder-bot command throttling · quote creation throttled
to stop price-list scraping · Celery queue depth alerts.

## 11. Audit logging

Logged with actor, action, resource, timestamp, IP, user agent and metadata: login and
failed login, order create/modify/cancel, payment submit/approve/reject, receipt view, bot
create/suspend/resume, configuration change, feature enable/disable, credential
create/rotate, price version create/close, all admin mutations, permission and role changes,
tenant member invite/remove.

Append-only: the application database role has no `UPDATE`/`DELETE` grant on `audit_log`.

## 12. Secrets management

`.env` is git-ignored; `.env.example` carries names and shapes only, never values. Production
secrets come from the orchestrator's secret store. `SECRET_KEY`, `ENCRYPTION_KEK`, database
and Redis URLs, storage keys and AI keys are all environment-injected. A pre-commit
secret-scanner blocks accidental commits. Distinct keys per environment; no production
secret ever exists on a developer machine.

## 13. Data protection

- Bot end-user data (a clinic's patients) is minimised: platform user id, display name,
  optional phone. No message content is retained beyond operational need.
- `inbound_update` raw payloads: 30-day retention, then purged.
- Analytics is aggregated wherever a metric does not require identity.
- Tenant deletion cascades to all tenant-scoped data with an export offered first.
- Receipts carry bank details — retention policy and restricted access, reviewed with legal.

## 14. Testing (spec §53)

`tests/security/` contains: cross-tenant sweep · unauthenticated access sweep · role
escalation attempts · token-leak response scan · upload validation (wrong MIME, oversize,
polyglot, SVG, traversal filename) · webhook forgery (missing/wrong/expired secret, replay) ·
order and payment illegal-transition attempts · rate-limit enforcement · IDOR on every
`public_id` route.

CI additionally runs dependency vulnerability scanning, `bandit`, and secret scanning; the
build fails on high-severity findings.
