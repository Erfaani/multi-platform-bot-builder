"""Telegram Mini App — end-user storefront/booking surface (Phase 10.5).

No website account, no session cookie: Telegram's own signed `initData` is the entire
authentication for this surface, exactly how Telegram's own docs describe WebApp auth.
Every request re-verifies it fresh — there is no mini-app-specific session token that
could be stolen or that needs its own expiry handling.

Bale is unaffected by any of this: `Capabilities.web_app` is false for Bale
(`apps.platforms.bale.adapter`), so nothing here is ever reached from a Bale bot.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from django.utils import timezone

from apps.bots import credentials as credential_service
from apps.bots.models import BotPlatformInstance
from apps.bot_runtime.models import BusinessContact
from apps.core.errors import PermissionDeniedError

#: Telegram recommends checking `auth_date` freshness; this is a storefront, not a
#: payment flow, so a generous window avoids the app failing just because a customer
#: left the chat open for a while before tapping in.
INIT_DATA_MAX_AGE_SECONDS = 86400


def verify_init_data(*, instance: BotPlatformInstance, raw_init_data: str) -> dict:
    """Verify Telegram's WebApp initData against this bot's own token.

    Raises `PermissionDeniedError` for anything that doesn't check out — a bad
    signature, a missing hash, or data older than `INIT_DATA_MAX_AGE_SECONDS`. Returns
    the parsed Telegram user dict (`id`, `first_name`, `username`, ...).
    """
    pairs = dict(parse_qsl(raw_init_data or "", strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise PermissionDeniedError(code="miniapp.missing_hash", message="Missing initData signature.")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))

    token = credential_service.read_token(instance=instance, purpose="miniapp_verify")
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise PermissionDeniedError(
            code="miniapp.bad_signature", message="Could not verify your Telegram identity."
        )

    try:
        auth_date = int(pairs.get("auth_date", 0))
    except ValueError:
        auth_date = 0
    if time.time() - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        raise PermissionDeniedError(
            code="miniapp.stale", message="This session has expired — please reopen the app."
        )

    user_raw = pairs.get("user")
    if not user_raw:
        raise PermissionDeniedError(code="miniapp.no_user", message="No Telegram user in initData.")

    try:
        return json.loads(user_raw)
    except (TypeError, ValueError) as exc:
        raise PermissionDeniedError(code="miniapp.bad_user", message="Malformed initData.") from exc


def upsert_contact(*, instance: BotPlatformInstance, telegram_user: dict) -> BusinessContact:
    """Same row a chat conversation with this bot would create — a customer who
    browses the Mini App then messages the bot (or vice versa) is one contact, not two.
    """
    display_name = f"{telegram_user.get('first_name', '')} {telegram_user.get('last_name', '')}".strip()
    contact, _ = BusinessContact.objects.update_or_create(
        bot_id=instance.bot_id,
        platform=instance.platform,
        platform_user_id=str(telegram_user["id"]),
        defaults={
            "tenant_id": instance.bot.tenant_id,
            "display_name": display_name[:128],
            "username": (telegram_user.get("username") or "")[:64],
            "locale": telegram_user.get("language_code", "en"),
            "last_seen_at": timezone.now(),
        },
    )
    return contact


def enabled_feature_slugs(bot) -> set[str]:
    return set(bot.bot_features.filter(is_enabled=True).values_list("feature__slug", flat=True))
