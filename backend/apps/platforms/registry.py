"""Adapter registry.

Everything that needs to know about a channel asks here, so adding WhatsApp later means
registering one adapter rather than editing the builder, the pricing engine and the
preview (spec §59).
"""

from __future__ import annotations

from apps.platforms.bale.adapter import BaleAdapter
from apps.platforms.base import Capabilities, PlatformAdapter
from apps.platforms.constants import SELLABLE_PLATFORMS, Platform
from apps.platforms.preview.adapter import PreviewAdapter
from apps.platforms.telegram.adapter import TelegramAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {}


def register(adapter: PlatformAdapter) -> None:
    _ADAPTERS[adapter.slug] = adapter


def get_adapter(slug: str) -> PlatformAdapter:
    try:
        return _ADAPTERS[slug]
    except KeyError as exc:
        raise LookupError(f"No adapter registered for platform {slug!r}.") from exc


def capabilities_for(slug: str) -> Capabilities:
    return get_adapter(slug).capabilities


def sellable_adapters() -> dict[str, PlatformAdapter]:
    """Adapters a customer may actually buy. Excludes `preview` by construction."""
    return {slug: _ADAPTERS[slug] for slug in SELLABLE_PLATFORMS if slug in _ADAPTERS}


def is_sellable(slug: str) -> bool:
    return slug in SELLABLE_PLATFORMS and slug in _ADAPTERS


register(TelegramAdapter())
register(BaleAdapter())
register(PreviewAdapter())

__all__ = [
    "register",
    "get_adapter",
    "capabilities_for",
    "sellable_adapters",
    "is_sellable",
    "Platform",
]
