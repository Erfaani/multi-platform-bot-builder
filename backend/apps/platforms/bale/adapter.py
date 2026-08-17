"""Bale adapter.

Bale exposes a Telegram-*shaped* API, not a Telegram-compatible one. These capabilities
are **provisional** (`verified=False`) until the Phase 5 spike confirms them against the
live API — see docs/00-ANALYSIS.md R-02.

Everything conservative here is deliberate: claiming a capability we do not have means
selling a customer a feature that fails silently in production, which is far worse than
degrading to a simpler presentation we know works.
"""

from __future__ import annotations

from typing import Any

from apps.platforms.base import Capabilities, InboundEvent
from apps.platforms.constants import Platform
from apps.platforms.rendering import CapabilityRenderer

#: Conservative starting manifest (BALE.md §3). Every ⚠️ value is a guess that
#: `manage.py probe_bale` is designed to replace with a measured one.
#:
#: Conservative means *understating* capability: a feature that degrades to a numbered
#: list still works, whereas one that claims inline keyboards it does not have simply
#: fails in front of a paying customer.
BALE_CAPABILITIES = Capabilities(
    inline_keyboards=True,       # ⚠️ Q2
    reply_keyboards=True,
    max_buttons_per_row=6,       # ⚠️ Q3
    max_buttons_total=60,        # ⚠️ Q3
    media_groups=False,          # ⚠️ Q6 — assumed absent until proven present
    message_editing=True,        # ⚠️ Q4
    web_app=False,               # documented as unsupported
    file_uploads=True,           # ⚠️ Q6
    max_text_length=4096,        # ⚠️ Q5
    verified=False,              # flipped only by a completed spike
)


class BaleAdapter(CapabilityRenderer):
    """Bale adapter.

    Deliberately **not** a subclass of the Telegram adapter. The two APIs are similar
    enough that inheritance would look tidy and hide precisely the differences that
    matter (docs/00-ANALYSIS.md R-02).
    """

    slug = Platform.BALE
    capabilities = BALE_CAPABILITIES
    display_name = "Bale"

    def parse(self, raw: dict[str, Any], instance_public_id: str) -> InboundEvent:
        """Normalise a Bale update.

        ⚠️ Spike Q8: field-level differences from Telegram are unconfirmed, so this reads
        defensively — every lookup tolerates an absent key rather than assuming the
        Telegram shape.
        """
        update_id = raw.get("update_id")

        callback = raw.get("callback_query") or {}
        if callback:
            message = callback.get("message") or {}
            user = callback.get("from") or callback.get("user") or {}
            chat = message.get("chat") or {}
            return InboundEvent(
                platform=self.slug,
                instance_public_id=instance_public_id,
                chat_ref=str(chat.get("id", "")),
                user_ref=str(user.get("id", "")),
                kind="callback",
                text=None,
                payload={
                    "data": callback.get("data", ""),
                    "callback_query_id": callback.get("id", ""),
                    "message_id": message.get("message_id"),
                },
                locale_hint=user.get("language_code"),
                user_display_name=self._display_name(user),
                username=user.get("username", "") or "",
                update_id=update_id,
            )

        message = raw.get("message") or raw.get("edited_message") or {}
        user = message.get("from") or {}
        chat = message.get("chat") or {}
        text = message.get("text")

        if message.get("contact"):
            kind = "contact"
        elif message.get("photo"):
            kind = "photo"
        elif text and text.startswith("/"):
            kind = "command"
        elif text:
            kind = "message"
        else:
            kind = "unknown"

        return InboundEvent(
            platform=self.slug,
            instance_public_id=instance_public_id,
            chat_ref=str(chat.get("id", "")),
            user_ref=str(user.get("id", "")),
            kind=kind,
            text=text,
            payload={
                "message_id": message.get("message_id"),
                "contact": message.get("contact"),
                "photo": message.get("photo"),
            },
            # Bale's user base is overwhelmingly Persian, so absent a hint that is the
            # better default than falling through to English.
            locale_hint=user.get("language_code") or "fa",
            user_display_name=self._display_name(user),
            username=user.get("username", "") or "",
            update_id=update_id,
        )

    @staticmethod
    def _display_name(user: dict) -> str:
        return " ".join(
            filter(None, [user.get("first_name", ""), user.get("last_name", "")])
        ).strip()
