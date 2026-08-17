"""Channel-independent contracts (ARCHITECTURE.md §4).

The core speaks in `Reply` objects: text keys, choices, attachments. It never knows
what an inline keyboard is. Adapters translate a `Reply` into whatever their platform
supports, degrading where a capability is missing.

This module is pure — no Django models, no network — so the whole rendering path is
testable without a database or a live bot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Capabilities",
    "Choice",
    "InboundEvent",
    "Reply",
    "Attachment",
    "RenderContext",
    "RenderedMessage",
    "ButtonLayout",
    "PlatformAdapter",
]


class ButtonLayout(str, Enum):
    """How choices ended up being presented, after degradation."""

    INLINE = "inline"
    REPLY = "reply"
    NUMBERED = "numbered"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a platform can actually do.

    Declared per adapter and treated as data: the builder refuses to sell a feature a
    platform cannot run, and the renderer degrades rather than emitting something the
    platform will reject at runtime.

    ``verified`` records whether these values were confirmed against the live API.
    Bale's are provisional until the Phase 5 spike (docs/00-ANALYSIS.md R-02) — shipping
    an unverified `True` would mean selling a feature that silently fails in production.
    """

    inline_keyboards: bool
    reply_keyboards: bool
    max_buttons_per_row: int
    max_buttons_total: int
    media_groups: bool
    message_editing: bool
    web_app: bool
    file_uploads: bool
    max_text_length: int
    verified: bool = False


@dataclass(frozen=True, slots=True)
class InboundEvent:
    """A platform update, normalised.

    The core never sees a Telegram `Update` or a Bale one — only this. Adding a channel
    means writing a `parse()` that produces this shape, and nothing downstream changes.
    """

    platform: str
    instance_public_id: str
    chat_ref: str
    user_ref: str
    kind: str  # message | command | callback | contact | photo | unknown
    text: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    locale_hint: str | None = None
    user_display_name: str = ""
    username: str = ""
    update_id: int | None = None

    @property
    def is_command(self) -> bool:
        return self.kind == "command"


@dataclass(frozen=True, slots=True)
class Choice:
    """One option offered to the user. ``label_key`` is a translation key, never text."""

    label_key: str
    value: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Attachment:
    kind: str  # image | document | location | contact
    ref: str
    caption_key: str | None = None


@dataclass(frozen=True, slots=True)
class Reply:
    """What a feature handler returns. Platform-free by construction."""

    text_key: str
    params: dict[str, Any] = field(default_factory=dict)
    choices: list[Choice] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    expects: str | None = None  # text | phone | photo | date | None


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Everything an adapter needs that is not part of the reply itself."""

    locale: str
    business_name: str = ""
    translate: Any = None  # callable(key, params, locale) -> str


@dataclass(slots=True)
class RenderedMessage:
    """An adapter's output, in a shape both a transport and a preview can consume."""

    text: str
    buttons: list[list[str]] = field(default_factory=list)
    layout: ButtonLayout = ButtonLayout.NONE
    attachments: list[Attachment] = field(default_factory=list)
    expects: str | None = None
    #: Human-readable notes about degradation, surfaced in the preview so a customer
    #: sees *why* Bale looks different from Telegram before they pay.
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class PlatformAdapter(Protocol):
    """The contract every channel implements."""

    slug: str
    capabilities: Capabilities

    def render(self, reply: Reply, ctx: RenderContext) -> RenderedMessage: ...


def chunk_buttons(labels: list[str], per_row: int) -> list[list[str]]:
    """Lay buttons out in rows of at most ``per_row``."""
    if per_row < 1:
        per_row = 1
    return [labels[i : i + per_row] for i in range(0, len(labels), per_row)]


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """Trim to the platform's message limit, reporting whether it was cut."""
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[: max(0, limit - 1)].rstrip() + "…", True
