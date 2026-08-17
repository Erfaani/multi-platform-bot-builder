"""Platform HTTP transport.

Two things this module exists to enforce:

1. **Egress profiles.** Telegram is typically unreachable from Iranian infrastructure and
   Bale is best reached from inside it (docs/00-ANALYSIS.md R-03). Base URL, proxy and
   timeouts are therefore per-platform configuration, never hard-coded, so the two can be
   scheduled onto different hosts without a code change.

2. **A seam for tests.** `FakeTransport` replays recorded responses, so the adapter
   conformance suite runs with no live network in CI (BOT_RUNTIME.md §8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class PlatformApiError(Exception):
    """A platform rejected the call."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
        retry_after: int | None = None,
        method: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after
        self.method = method

    @property
    def is_rate_limited(self) -> bool:
        return self.status_code == 429 or self.error_code == 429

    @property
    def is_permanent(self) -> bool:
        """Retrying will not help: bad token, blocked by the user, chat gone."""
        return self.status_code in {400, 401, 403, 404}


@dataclass(frozen=True, slots=True)
class EgressProfile:
    base_url: str
    proxy: str | None = None
    timeout_seconds: float = 20.0
    verify_tls: bool = True


def egress_profile_for(platform: str) -> EgressProfile:
    """Resolve a platform's egress settings from configuration."""
    profiles = getattr(settings, "PLATFORM_EGRESS", {})
    raw = profiles.get(platform, {})
    if not raw.get("base_url"):
        raise PlatformApiError(f"No egress profile configured for platform {platform!r}.")
    return EgressProfile(
        base_url=raw["base_url"],
        proxy=raw.get("proxy") or None,
        timeout_seconds=float(raw.get("timeout_seconds", 20.0)),
        verify_tls=bool(raw.get("verify_tls", True)),
    )


class Transport(Protocol):
    def call(self, token: str, method: str, payload: dict[str, Any] | None = None) -> dict: ...


class HttpTransport:
    """Real Bot API transport for Telegram-shaped APIs.

    Both Telegram and Bale expose `{base}/bot{token}/{method}` returning
    `{"ok": bool, "result": ..., "description": ..., "error_code": ...}`.
    """

    def __init__(self, profile: EgressProfile) -> None:
        self.profile = profile

    def call(self, token: str, method: str, payload: dict[str, Any] | None = None) -> dict:
        url = f"{self.profile.base_url.rstrip('/')}/bot{token}/{method}"

        try:
            with httpx.Client(
                timeout=self.profile.timeout_seconds,
                proxy=self.profile.proxy,
                verify=self.profile.verify_tls,
            ) as client:
                response = client.post(url, json=payload or {})
        except httpx.RequestError as exc:
            # The token is in the URL, so never let the exception text escape verbatim.
            raise PlatformApiError(
                f"Could not reach the platform API ({type(exc).__name__}).", method=method
            ) from None

        return self._unwrap(response, method)

    @staticmethod
    def _unwrap(response: httpx.Response, method: str) -> dict:
        try:
            body = response.json()
        except ValueError:
            raise PlatformApiError(
                f"Platform returned a non-JSON response ({response.status_code}).",
                status_code=response.status_code,
                method=method,
            ) from None

        if response.is_success and body.get("ok"):
            return body.get("result", {})

        retry_after = None
        parameters = body.get("parameters") or {}
        if "retry_after" in parameters:
            retry_after = int(parameters["retry_after"])

        raise PlatformApiError(
            body.get("description") or f"Platform rejected {method}.",
            status_code=response.status_code,
            error_code=body.get("error_code"),
            retry_after=retry_after,
            method=method,
        )


@dataclass
class FakeTransport:
    """Records calls and replays canned responses. Used by tests and the conformance suite."""

    responses: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    #: Methods that should raise, mapped to the error to raise.
    failures: dict[str, PlatformApiError] = field(default_factory=dict)

    def call(self, token: str, method: str, payload: dict[str, Any] | None = None) -> dict:
        self.calls.append((method, payload or {}))

        if method in self.failures:
            raise self.failures[method]

        if method not in self.responses:
            raise PlatformApiError(f"FakeTransport has no response for {method!r}.", method=method)

        result = self.responses[method]
        if not callable(result):
            return result

        # Callables receive the token too, so a fake can return a *different* identity
        # per token — the real API does, and a fake that does not hides bugs where one
        # bot's identity overwrites another's.
        return result(payload or {}, token)

    def called(self, method: str) -> bool:
        return any(name == method for name, _ in self.calls)

    def payload_for(self, method: str) -> dict:
        for name, payload in self.calls:
            if name == method:
                return payload
        raise AssertionError(f"{method} was never called.")


#: Swapped by tests via `override_transport`.
_transport_override: Transport | None = None


def get_transport(platform: str) -> Transport:
    if _transport_override is not None:
        return _transport_override
    return HttpTransport(egress_profile_for(platform))


def override_transport(transport: Transport | None) -> None:
    """Install a transport for every platform. Tests only."""
    global _transport_override
    _transport_override = transport
