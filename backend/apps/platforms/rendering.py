"""The degradation ladder, shared by every adapter.

Rendering is capability-driven, so there is exactly one implementation of "what does a
menu look like when the platform has no inline keyboards". Adapters supply capabilities
and a transport; they do not each reinvent layout — that is how the two channels drift
apart and the "no duplicated business logic" rule quietly dies (spec §61.1).

Ladder:
    inline keyboard → reply keyboard → numbered text menu
    media group     → sequential sends
    edit message    → send a new message
"""

from __future__ import annotations

from apps.platforms.base import (
    ButtonLayout,
    Capabilities,
    Reply,
    RenderContext,
    RenderedMessage,
    chunk_buttons,
    truncate,
)


def _translate(ctx: RenderContext, key: str, params: dict | None = None) -> str:
    if ctx.translate is not None:
        return ctx.translate(key, params or {}, ctx.locale)
    # No catalogue bound: show the key. Silently rendering an empty string would hide
    # a missing translation until a customer saw a blank menu (I18N.md §6).
    return key


def render_with_capabilities(
    reply: Reply, ctx: RenderContext, capabilities: Capabilities
) -> RenderedMessage:
    text = _translate(ctx, reply.text_key, reply.params)
    notes: list[str] = []

    labels = [_translate(ctx, choice.label_key, choice.params) for choice in reply.choices]

    if not labels:
        layout: ButtonLayout = ButtonLayout.NONE
        buttons: list[list[str]] = []
    elif capabilities.inline_keyboards:
        layout = ButtonLayout.INLINE
        buttons = chunk_buttons(labels, capabilities.max_buttons_per_row)
    elif capabilities.reply_keyboards:
        layout = ButtonLayout.REPLY
        buttons = chunk_buttons(labels, capabilities.max_buttons_per_row)
        notes.append("Inline keyboards are unavailable; using a reply keyboard.")
    else:
        layout = ButtonLayout.NUMBERED
        buttons = []
        numbered = "\n".join(f"{index}. {label}" for index, label in enumerate(labels, start=1))
        text = f"{text}\n\n{numbered}"
        notes.append("Buttons are unavailable; options are presented as a numbered list.")

    # Too many buttons for one screen is a real platform limit, not a nicety.
    if buttons and capabilities.max_buttons_total:
        total = sum(len(row) for row in buttons)
        if total > capabilities.max_buttons_total:
            kept: list[list[str]] = []
            remaining = capabilities.max_buttons_total
            for row in buttons:
                if remaining <= 0:
                    break
                kept.append(row[:remaining])
                remaining -= len(kept[-1])
            buttons = kept
            notes.append(
                f"Only the first {capabilities.max_buttons_total} options fit on one screen; "
                "the rest need pagination."
            )

    text, was_truncated = truncate(text, capabilities.max_text_length)
    if was_truncated:
        notes.append(
            f"Message exceeds the {capabilities.max_text_length}-character limit and was trimmed."
        )

    attachments = list(reply.attachments)
    if len(attachments) > 1 and not capabilities.media_groups:
        notes.append("Media groups are unsupported; attachments are sent one at a time.")

    return RenderedMessage(
        text=text,
        buttons=buttons,
        layout=layout,
        attachments=attachments,
        expects=reply.expects,
        notes=notes,
    )


class CapabilityRenderer:
    """Mixin giving an adapter the shared ladder."""

    capabilities: Capabilities

    def render(self, reply: Reply, ctx: RenderContext) -> RenderedMessage:
        return render_with_capabilities(reply, ctx, self.capabilities)
