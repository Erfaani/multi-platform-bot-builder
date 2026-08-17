"""Platform API client registry.

Before this existed, the Outbound Gateway imported `TelegramApi` directly — which meant
"the only code allowed to call a platform API" could only call *one* platform. Adding
Bale would have required a second branch in the gateway, and a third for every channel
after that.

Callers now ask for a client by platform. Adding a channel is a registration, not an edit
to the runtime (spec §59).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from apps.platforms.constants import Platform


@runtime_checkable
class BotApiClient(Protocol):
    """What the runtime and provisioning need from any channel."""

    platform: str

    def get_me(self) -> Any: ...
    def set_webhook(self, url: str, secret_token: str, allowed_updates: list[str] | None = None) -> None: ...
    def delete_webhook(self, drop_pending_updates: bool = True) -> None: ...
    def set_my_commands(self, commands: list[dict], language_code: str = "") -> None: ...
    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict: ...


_FACTORIES: dict[str, Any] = {}


def register_client(platform: str, factory) -> None:
    _FACTORIES[platform] = factory


def get_client(platform: str, token: str) -> BotApiClient:
    """Build a short-lived client for one platform and token."""
    try:
        factory = _FACTORIES[platform]
    except KeyError as exc:
        raise LookupError(
            f"No API client registered for platform {platform!r}. "
            "It is not implemented yet."
        ) from exc
    return factory(token)


def has_client(platform: str) -> bool:
    return platform in _FACTORIES


def supported_platforms() -> set[str]:
    return set(_FACTORIES)


def _register_builtin() -> None:
    from apps.platforms.bale.api import BaleApi
    from apps.platforms.telegram.api import TelegramApi

    register_client(Platform.TELEGRAM, TelegramApi)
    register_client(Platform.BALE, BaleApi)


_register_builtin()
