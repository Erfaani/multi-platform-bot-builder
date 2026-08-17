"""Envelope encryption for secrets at rest.

A fresh 256-bit data key (DEK) encrypts each value with AES-GCM; the DEK is then
wrapped by the key-encryption key (KEK) from the environment. Every ciphertext
records the KEK version that wrapped it, so keys can be rotated without downtime
and without a flag day (SECURITY.md §5).

Used from Phase 4 for bot credentials. Built now because it is foundational, small,
and much harder to retrofit once tokens already exist in the database.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

NONCE_BYTES = 12
DEK_BYTES = 32
_ENVELOPE_VERSION = 1


class DecryptionError(Exception):
    """Ciphertext could not be decrypted with any known key."""


@dataclass(frozen=True, slots=True)
class Envelope:
    version: int
    kek_version: int
    wrapped_dek: bytes
    dek_nonce: bytes
    ciphertext: bytes
    nonce: bytes

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "v": self.version,
                "k": self.kek_version,
                "wd": base64.b64encode(self.wrapped_dek).decode(),
                "dn": base64.b64encode(self.dek_nonce).decode(),
                "ct": base64.b64encode(self.ciphertext).decode(),
                "n": base64.b64encode(self.nonce).decode(),
            }
        ).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> Envelope:
        try:
            data = json.loads(raw.decode())
            return cls(
                version=data["v"],
                kek_version=data["k"],
                wrapped_dek=base64.b64decode(data["wd"]),
                dek_nonce=base64.b64decode(data["dn"]),
                ciphertext=base64.b64decode(data["ct"]),
                nonce=base64.b64decode(data["n"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise DecryptionError("Malformed encryption envelope.") from exc


def _load_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("ENCRYPTION_KEK must be base64-encoded.") from exc
    if len(key) != DEK_BYTES:
        raise ImproperlyConfigured(
            f"ENCRYPTION_KEK must decode to {DEK_BYTES} bytes, got {len(key)}."
        )
    return key


def _keyring() -> dict[int, bytes]:
    """Current KEK plus any previous ones, so old ciphertext stays readable."""
    if not settings.ENCRYPTION_KEK:
        raise ImproperlyConfigured("ENCRYPTION_KEK is not configured.")
    keys = {int(settings.ENCRYPTION_KEK_VERSION): _load_key(settings.ENCRYPTION_KEK)}
    previous = getattr(settings, "ENCRYPTION_KEK_PREVIOUS", "") or ""
    for entry in filter(None, (part.strip() for part in previous.split(","))):
        version, _, material = entry.partition(":")
        keys[int(version)] = _load_key(material)
    return keys


def encrypt(plaintext: str, *, associated_data: bytes = b"") -> bytes:
    """Encrypt with a fresh DEK wrapped by the current KEK."""
    keys = _keyring()
    kek_version = int(settings.ENCRYPTION_KEK_VERSION)
    kek = keys[kek_version]

    dek = os.urandom(DEK_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode(), associated_data)

    dek_nonce = os.urandom(NONCE_BYTES)
    wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, None)

    return Envelope(
        version=_ENVELOPE_VERSION,
        kek_version=kek_version,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        ciphertext=ciphertext,
        nonce=nonce,
    ).to_bytes()


def decrypt(raw: bytes, *, associated_data: bytes = b"") -> str:
    envelope = Envelope.from_bytes(raw)
    keys = _keyring()
    kek = keys.get(envelope.kek_version)
    if kek is None:
        raise DecryptionError(
            f"No KEK available for version {envelope.kek_version}; "
            "add it to ENCRYPTION_KEK_PREVIOUS."
        )
    try:
        dek = AESGCM(kek).decrypt(envelope.dek_nonce, envelope.wrapped_dek, None)
        return AESGCM(dek).decrypt(envelope.nonce, envelope.ciphertext, associated_data).decode()
    except Exception as exc:  # cryptography raises InvalidTag
        raise DecryptionError("Could not decrypt value.") from exc


def fingerprint(plaintext: str) -> str:
    """Stable, non-reversible identifier for equality checks without decrypting.

    Lets us detect "this token is already registered to another tenant" without
    ever holding two plaintexts side by side.
    """
    import hashlib
    import hmac

    keys = _keyring()
    kek = keys[int(settings.ENCRYPTION_KEK_VERSION)]
    return hmac.new(kek, plaintext.encode(), hashlib.sha256).hexdigest()
