"""Per-platform provisioning operations.

The saga is channel-independent; the platform-specific calls live here. Telegram
registers in Phase 4, Bale in Phase 5.

A platform with no registered provisioner is **deferred, not failed**: the instance row
is created and left `PENDING` so the customer can see it is coming, and it does not block
activation of the channels that are ready. Marking it `FAILED` would tell a paying
customer something broke when nothing did.
"""

from __future__ import annotations

import logging
from typing import Protocol

from apps.platforms.constants import Platform

logger = logging.getLogger(__name__)


class PlatformProvisioner(Protocol):
    platform: str

    def verify(self, token: str): ...
    def apply_branding(self, token: str, *, name: str, description: str, short: str) -> None: ...
    def set_commands(self, token: str, commands: list[dict], language_code: str = "") -> None: ...
    def set_webhook(self, token: str, url: str, secret: str) -> None: ...
    def delete_webhook(self, token: str) -> None: ...


class TelegramProvisioner:
    platform = Platform.TELEGRAM

    def verify(self, token: str):
        from apps.platforms.telegram.api import verify_token

        return verify_token(token)

    def apply_branding(self, token: str, *, name: str, description: str, short: str) -> None:
        from apps.platforms.telegram.api import TelegramApi

        api = TelegramApi(token)
        if name:
            api.set_my_name(name)
        if description:
            api.set_my_description(description)
        if short:
            api.set_my_short_description(short)

    def set_commands(self, token: str, commands: list[dict], language_code: str = "") -> None:
        from apps.platforms.telegram.api import TelegramApi

        TelegramApi(token).set_my_commands(commands, language_code)

    def set_webhook(self, token: str, url: str, secret: str) -> None:
        from apps.platforms.telegram.api import TelegramApi

        TelegramApi(token).set_webhook(url, secret)

    def delete_webhook(self, token: str) -> None:
        from apps.platforms.telegram.api import TelegramApi

        TelegramApi(token).delete_webhook()


class BaleProvisioner:
    """Bale provisioning.

    Branding and command registration are treated as **best-effort**: whether Bale
    implements `setMyName` / `setMyCommands` is spike question 7, and a missing
    branding call must not fail a paid order. A bot that works but is not renamed is a
    cosmetic problem; a failed order is not.
    """

    platform = Platform.BALE

    def verify(self, token: str):
        from apps.platforms.bale.api import verify_token

        return verify_token(token)

    def apply_branding(self, token: str, *, name: str, description: str, short: str) -> None:
        from apps.platforms.bale.api import BaleApi
        from apps.platforms.transport import PlatformApiError

        api = BaleApi(token)
        for call, value in ((api.set_my_name, name), (api.set_my_description, description)):
            if not value:
                continue
            try:
                call(value)
            except PlatformApiError as exc:
                if exc.is_permanent:
                    logger.info(
                        "Bale does not support %s; skipping (spike Q7).", exc.method
                    )
                    continue
                raise

    def set_commands(self, token: str, commands: list[dict], language_code: str = "") -> None:
        from apps.platforms.bale.api import BaleApi
        from apps.platforms.transport import PlatformApiError

        try:
            BaleApi(token).set_my_commands(commands, language_code)
        except PlatformApiError as exc:
            if exc.is_permanent:
                logger.info("Bale does not support setMyCommands; skipping (spike Q7).")
                return
            raise

    def set_webhook(self, token: str, url: str, secret: str) -> None:
        from apps.platforms.bale.api import BaleApi

        # Not tolerant of failure: without a webhook the bot cannot receive anything,
        # which is not a cosmetic problem.
        BaleApi(token).set_webhook(url, secret)

    def delete_webhook(self, token: str) -> None:
        from apps.platforms.bale.api import BaleApi

        BaleApi(token).delete_webhook()


_PROVISIONERS: dict[str, PlatformProvisioner] = {
    TelegramProvisioner.platform: TelegramProvisioner(),
    BaleProvisioner.platform: BaleProvisioner(),
}


def register(provisioner: PlatformProvisioner) -> None:
    _PROVISIONERS[provisioner.platform] = provisioner


def get_provisioner(platform: str) -> PlatformProvisioner | None:
    """None means "not implemented yet" — the caller defers rather than fails."""
    return _PROVISIONERS.get(platform)


def supported_platforms() -> set[str]:
    return set(_PROVISIONERS)
