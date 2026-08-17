"""Provider abstraction: the answering model is swappable without touching `services.py`.

Anthropic is the only implementation today (`anthropic_provider.py`), matching this
project's `AI_PROVIDER` setting default — but `services.answer_question()` only ever talks
to this narrow interface, so adding a second provider is a new module here, not a rewrite
of the orchestration logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class AiProviderError(Exception):
    """The provider could not produce an answer (timeout, auth, rate limit, ...).

    Always caught by `services.answer_question()` and turned into a graceful bot reply —
    never allowed to bubble into the dispatcher, which would otherwise reset the
    customer's session and show the generic error message instead of a targeted one.
    """


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class AiProvider(ABC):
    @abstractmethod
    def generate(self, *, system: str, question: str, model: str) -> ProviderResponse:
        """Answer `question` given a fully-assembled `system` prompt (persona + grounding)."""
