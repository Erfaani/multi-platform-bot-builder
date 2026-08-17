"""Signed callback payloads.

Callback data comes back from the user's client, so it is attacker-controlled: without a
signature anyone could craft `callback_data` invoking a route they were never offered.

Telegram caps `callback_data` at **64 bytes**, so the format has to be compact:

    v1.<sig8>.<route>.<value>

The signature is a truncated HMAC over route+value keyed by the bot instance, so a token
minted for one bot cannot be replayed against another.
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings

VERSION = "v1"
SIG_LENGTH = 8
MAX_CALLBACK_BYTES = 64


class InvalidCallback(ValueError):
    """The payload was malformed, or its signature did not verify."""


def _secret(instance_public_id: str) -> bytes:
    return hashlib.sha256(
        f"{settings.SECRET_KEY}:{instance_public_id}".encode()
    ).digest()


def _sign(instance_public_id: str, route: str, value: str) -> str:
    digest = hmac.new(
        _secret(instance_public_id), f"{route}.{value}".encode(), hashlib.sha256
    ).hexdigest()
    return digest[:SIG_LENGTH]


def encode(instance_public_id: str, route: str, value: str = "") -> str:
    """Build a signed callback payload, or raise if it will not fit."""
    payload = f"{VERSION}.{_sign(instance_public_id, route, value)}.{route}.{value}"

    if len(payload.encode()) > MAX_CALLBACK_BYTES:
        # Better to fail loudly in a test than to have the platform silently reject
        # the button at runtime.
        raise InvalidCallback(
            f"Callback payload is {len(payload.encode())} bytes, over the "
            f"{MAX_CALLBACK_BYTES}-byte limit: {route}.{value}"
        )
    return payload


def decode(instance_public_id: str, payload: str) -> tuple[str, str]:
    """Verify and unpack a callback payload into `(route, value)`."""
    parts = (payload or "").split(".", 3)
    if len(parts) < 3 or parts[0] != VERSION:
        raise InvalidCallback("Unrecognised callback payload.")

    _, signature, route = parts[0], parts[1], parts[2]
    value = parts[3] if len(parts) > 3 else ""

    expected = _sign(instance_public_id, route, value)
    if not hmac.compare_digest(signature, expected):
        raise InvalidCallback("Callback signature did not verify.")

    return route, value
