"""The Anthropic (Claude) implementation of `AiProvider`.

A short, ungrounded-by-default customer support answer needs neither thinking nor a large
output budget — `settings.AI_MAX_OUTPUT_TOKENS` defaults to 1024, comfortably under the
non-streaming timeout guidance for any current Claude model, so this calls
`client.messages.create()` directly rather than streaming.
"""

from __future__ import annotations

import logging

import anthropic
from django.conf import settings

from apps.ai.providers.base import AiProvider, AiProviderError, ProviderResponse

logger = logging.getLogger(__name__)


class AnthropicProvider(AiProvider):
    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    def _client_or_raise(self) -> anthropic.Anthropic:
        if not settings.ANTHROPIC_API_KEY:
            raise AiProviderError("ANTHROPIC_API_KEY is not configured.")
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=settings.ANTHROPIC_API_KEY,
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
        return self._client

    def generate(self, *, system: str, question: str, model: str) -> ProviderResponse:
        client = self._client_or_raise()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": question}],
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            logger.warning("AI assistant provider call failed: %s", exc)
            raise AiProviderError(str(exc)) from exc

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        return ProviderResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
