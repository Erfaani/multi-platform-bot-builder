"""Telegram adapter.

Phase 2 supplies the declarative half — capabilities and rendering — which is what the
builder, the pricing engine and the preview need. The transport (webhooks, outbound
gateway, provisioning) lands in Phase 4.
"""

from __future__ import annotations

from typing import Any

from apps.platforms.base import Capabilities, InboundEvent
from apps.platforms.constants import Platform
from apps.platforms.rendering import CapabilityRenderer

#: Confirmed against the published Bot API limits.
TELEGRAM_CAPABILITIES = Capabilities(
    inline_keyboards=True,
    reply_keyboards=True,
    max_buttons_per_row=8,
    max_buttons_total=100,
    media_groups=True,
    message_editing=True,
    web_app=True,
    file_uploads=True,
    max_text_length=4096,
    verified=True,
)


class TelegramAdapter(CapabilityRenderer):
    slug = Platform.TELEGRAM
    capabilities = TELEGRAM_CAPABILITIES
    display_name = "Telegram"

    def parse(self, raw: dict[str, Any], instance_public_id: str) -> InboundEvent:
        """Normalise a Telegram `Update` into the platform-free shape.

        Everything Telegram-specific about inbound data stops here.
        """
        update_id = raw.get("update_id")

        callback = raw.get("callback_query")
        if callback:
            message = callback.get("message") or {}
            user = callback.get("from") or {}
            return InboundEvent(
                platform=self.slug,
                instance_public_id=instance_public_id,
                chat_ref=str((message.get("chat") or {}).get("id", "")),
                user_ref=str(user.get("id", "")),
                kind="callback",
                text=None,
                payload={
                    "data": callback.get("data", ""),
                    "callback_query_id": callback.get("id", ""),
                    "message_id": message.get("message_id"),
                },
                locale_hint=user.get("language_code"),
                user_display_name=" ".join(
                    filter(None, [user.get("first_name", ""), user.get("last_name", "")])
                ).strip(),
                username=user.get("username", ""),
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
            locale_hint=user.get("language_code"),
            user_display_name=" ".join(
                filter(None, [user.get("first_name", ""), user.get("last_name", "")])
            ).strip(),
            username=user.get("username", ""),
            update_id=update_id,
        )
