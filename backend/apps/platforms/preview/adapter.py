"""Preview adapter (spec §48, improvement #5 in docs/00-ANALYSIS.md).

Renders a `Reply` to JSON for the browser preview. It is a *third adapter over the same
core*, not a mock of the site: if the core ever grows a Telegram-shaped assumption, the
preview breaks too, which is exactly the alarm we want.

It renders **as a target platform** — passing Bale's capabilities shows the customer the
degraded Bale layout before they pay, rather than a Telegram screenshot that turns out
to be a promise we cannot keep.
"""

from __future__ import annotations

from dataclasses import asdict

from apps.platforms.base import (
    Capabilities,
    Reply,
    RenderContext,
    RenderedMessage,
)
from apps.platforms.constants import PREVIEW
from apps.platforms.rendering import render_with_capabilities

#: Permissive by design: when previewing "the bot" without choosing a channel, we show
#: the richest form. Any real platform can only degrade from here.
PREVIEW_CAPABILITIES = Capabilities(
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


class PreviewAdapter:
    slug = PREVIEW
    capabilities = PREVIEW_CAPABILITIES
    display_name = "Preview"

    def render(self, reply: Reply, ctx: RenderContext) -> RenderedMessage:
        return render_with_capabilities(reply, ctx, self.capabilities)

    def render_as(
        self, reply: Reply, ctx: RenderContext, capabilities: Capabilities
    ) -> RenderedMessage:
        """Render as another platform would, so the preview matches what ships."""
        return render_with_capabilities(reply, ctx, capabilities)

    @staticmethod
    def to_json(message: RenderedMessage) -> dict:
        payload = asdict(message)
        payload["layout"] = message.layout.value
        return payload
