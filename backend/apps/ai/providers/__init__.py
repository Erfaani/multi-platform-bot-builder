"""Factory for the configured `AiProvider` — see `base.py` for the interface it satisfies."""

from __future__ import annotations

from django.conf import settings

from apps.ai.providers.base import AiProvider, AiProviderError, ProviderResponse

__all__ = ["AiProvider", "AiProviderError", "ProviderResponse", "get_provider"]

_REGISTRY: dict[str, type[AiProvider]] = {}


def _registry() -> dict[str, type[AiProvider]]:
    if not _REGISTRY:
        from apps.ai.providers.anthropic_provider import AnthropicProvider

        _REGISTRY["anthropic"] = AnthropicProvider
    return _REGISTRY


def get_provider() -> AiProvider:
    provider_cls = _registry().get(settings.AI_PROVIDER)
    if provider_cls is None:
        raise AiProviderError(f"Unknown AI provider '{settings.AI_PROVIDER}'.")
    return provider_cls()
