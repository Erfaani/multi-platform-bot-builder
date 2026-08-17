"""Bale Bot API operations.

Written independently of the Telegram client on purpose. Bale's API is Telegram-*shaped*,
not Telegram-compatible, and `BaleApi(TelegramApi)` would silently inherit behaviour Bale
does not have — producing methods that appear to work and fail in production for exactly
the features a customer paid for (docs/00-ANALYSIS.md R-02, BALE.md §3).

Everything here is marked with its verification status. Anything ⚠️ is provisional until
`manage.py probe_bale` is run against a real bot and BALE.md §2 is filled in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.platforms.constants import Platform
from apps.platforms.transport import PlatformApiError, get_transport


@dataclass(frozen=True, slots=True)
class BotIdentity:
    platform_bot_id: str
    username: str
    display_name: str


class BaleApi:
    """Thin, typed wrapper over Bale's Bot API."""

    platform = Platform.BALE

    def __init__(self, token: str) -> None:
        self._token = token
        self._transport = get_transport(self.platform)

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        return self._transport.call(self._token, method, payload)

    # -- identity ---------------------------------------------------------
    def get_me(self) -> BotIdentity:
        """Validate a token and learn who it belongs to. (Confirmed to exist.)"""
        result = self._call("getMe")
        return BotIdentity(
            platform_bot_id=str(result.get("id", "")),
            username=result.get("username", ""),
            display_name=result.get("first_name", ""),
        )

    # -- branding ---------------------------------------------------------
    # ⚠️ Spike Q7. Bale may not implement these; provisioning treats them as optional
    # and records the outcome rather than failing the order over branding.
    def set_my_name(self, name: str, language_code: str = "") -> None:
        payload: dict[str, Any] = {"name": name[:64]}
        if language_code:
            payload["language_code"] = language_code
        self._call("setMyName", payload)

    def set_my_description(self, description: str, language_code: str = "") -> None:
        payload: dict[str, Any] = {"description": description[:512]}
        if language_code:
            payload["language_code"] = language_code
        self._call("setMyDescription", payload)

    def set_my_commands(self, commands: list[dict], language_code: str = "") -> None:
        payload: dict[str, Any] = {"commands": commands}
        if language_code:
            payload["language_code"] = language_code
        self._call("setMyCommands", payload)

    # -- webhook ----------------------------------------------------------
    def set_webhook(
        self, url: str, secret_token: str, allowed_updates: list[str] | None = None
    ) -> None:
        """Register the webhook.

        ⚠️ Spike Q1: whether Bale honours a `secret_token` is unconfirmed. The payload
        sends it regardless — an ignored field is harmless — and ingress additionally
        accepts an HMAC body signature, so authentication does not depend on the answer.
        """
        self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": allowed_updates or ["message", "callback_query"],
            },
        )

    def delete_webhook(self, drop_pending_updates: bool = True) -> None:
        self._call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def get_webhook_info(self) -> dict:
        return self._call("getWebhookInfo")

    def get_updates(self, offset: int | None = None, limit: int = 100) -> list[dict]:
        """Polling fallback, used if the spike shows webhooks are unavailable."""
        payload: dict[str, Any] = {"limit": limit}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload) or []

    # -- messaging (called only by the Outbound Gateway) -------------------
    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        """⚠️ Spike Q4. If absent, the user simply sees no 'loading' acknowledgement."""
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        self._call("answerCallbackQuery", payload)


def verify_token(token: str) -> BotIdentity:
    """Validate a Bale token by asking the platform who it is."""
    try:
        return BaleApi(token).get_me()
    except PlatformApiError as exc:
        if exc.is_permanent:
            raise PlatformApiError(
                "Bale rejected that token. Check you copied all of it.",
                status_code=exc.status_code,
                method="getMe",
            ) from None
        raise
