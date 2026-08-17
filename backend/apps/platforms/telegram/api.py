"""Telegram Bot API operations the platform needs.

Deliberately small: provisioning and the outbound gateway are the only callers, and the
gateway is the only code allowed to send messages (BOT_RUNTIME.md §1).

Note what is absent — there is no `createBot`. Telegram has no such method, which is the
whole reason ADR-0002 exists.
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
    can_join_groups: bool = False
    supports_inline_queries: bool = False


class TelegramApi:
    """Thin, typed wrapper. One instance per token, short-lived."""

    platform = Platform.TELEGRAM

    def __init__(self, token: str) -> None:
        self._token = token
        self._transport = get_transport(self.platform)

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        return self._transport.call(self._token, method, payload)

    # -- identity ---------------------------------------------------------
    def get_me(self) -> BotIdentity:
        """Validate a token and learn who it belongs to."""
        result = self._call("getMe")
        return BotIdentity(
            platform_bot_id=str(result.get("id", "")),
            username=result.get("username", ""),
            display_name=result.get("first_name", ""),
            can_join_groups=bool(result.get("can_join_groups", False)),
            supports_inline_queries=bool(result.get("supports_inline_queries", False)),
        )

    # -- branding ---------------------------------------------------------
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

    def set_my_short_description(self, text: str, language_code: str = "") -> None:
        payload: dict[str, Any] = {"short_description": text[:120]}
        if language_code:
            payload["language_code"] = language_code
        self._call("setMyShortDescription", payload)

    def set_my_commands(self, commands: list[dict], language_code: str = "") -> None:
        payload: dict[str, Any] = {"commands": commands}
        if language_code:
            payload["language_code"] = language_code
        self._call("setMyCommands", payload)

    # -- webhook ----------------------------------------------------------
    def set_webhook(
        self, url: str, secret_token: str, allowed_updates: list[str] | None = None
    ) -> None:
        self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": allowed_updates or ["message", "callback_query"],
                # A queue of stale updates from before provisioning helps nobody.
                "drop_pending_updates": True,
                "max_connections": 40,
            },
        )

    def delete_webhook(self, drop_pending_updates: bool = True) -> None:
        self._call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def get_webhook_info(self) -> dict:
        return self._call("getWebhookInfo")

    # -- messaging (called only by the Outbound Gateway) -------------------
    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": disable_notification,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        self._call("answerCallbackQuery", payload)


def verify_token(token: str) -> BotIdentity:
    """Validate a token by asking the platform who it is.

    Used by both provisioning strategies: the pool verifies stock, and token handoff
    verifies what the customer pasted before anything is stored.
    """
    try:
        return TelegramApi(token).get_me()
    except PlatformApiError as exc:
        if exc.is_permanent:
            raise PlatformApiError(
                "Telegram rejected that token. Check you copied all of it from BotFather.",
                status_code=exc.status_code,
                method="getMe",
            ) from None
        raise
