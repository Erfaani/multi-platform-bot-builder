"""Secrets must never reach a client or a log line (SECURITY.md §5).

Written now, before Phase 4 introduces real bot tokens, so the guard exists before
the thing it guards.
"""

from __future__ import annotations

import logging
import re

import pytest

from apps.core.encryption import DecryptionError, decrypt, encrypt, fingerprint
from apps.core.logging import REDACTED, SecretRedactingFilter, redact

TOKEN_SHAPE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
FAKE_TOKEN = "123456789:AAHfakefakefakefakefakefakefakefake1"


class TestLogRedaction:
    def test_bot_token_shape_is_redacted(self):
        assert TOKEN_SHAPE.search(redact(f"calling with {FAKE_TOKEN}")) is None

    def test_bearer_tokens_are_redacted(self):
        assert "eyJhbGciOiJIUzI1NiIsInR5" not in redact(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
        )

    def test_key_value_secrets_are_redacted(self):
        assert REDACTED in redact('{"api_key": "sk-verysecretvalue123456"}')
        assert REDACTED in redact("password=hunter2hunter2")

    def test_filter_rewrites_the_log_record(self):
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname="", lineno=0,
            msg="token %s", args=(FAKE_TOKEN,), exc_info=None,
        )
        SecretRedactingFilter().filter(record)
        assert TOKEN_SHAPE.search(record.getMessage()) is None

    def test_ordinary_messages_are_untouched(self):
        assert redact("order 10042 moved to PAID") == "order 10042 moved to PAID"


class TestEnvelopeEncryption:
    def test_round_trip(self):
        assert decrypt(encrypt(FAKE_TOKEN)) == FAKE_TOKEN

    def test_ciphertext_does_not_contain_the_plaintext(self):
        assert FAKE_TOKEN.encode() not in encrypt(FAKE_TOKEN)

    def test_each_encryption_is_unique(self):
        """A fresh DEK and nonce each time, so identical inputs are not correlatable."""
        assert encrypt(FAKE_TOKEN) != encrypt(FAKE_TOKEN)

    def test_tampered_ciphertext_is_rejected(self):
        blob = bytearray(encrypt(FAKE_TOKEN))
        blob[-8] = blob[-8] ^ 0xFF
        with pytest.raises(DecryptionError):
            decrypt(bytes(blob))

    def test_malformed_envelope_is_rejected(self):
        with pytest.raises(DecryptionError):
            decrypt(b"not-an-envelope")

    def test_associated_data_must_match(self):
        blob = encrypt(FAKE_TOKEN, associated_data=b"bot:1")
        with pytest.raises(DecryptionError):
            decrypt(blob, associated_data=b"bot:2")

    def test_fingerprint_is_stable_and_not_reversible(self):
        first = fingerprint(FAKE_TOKEN)
        assert first == fingerprint(FAKE_TOKEN)
        assert first != fingerprint(FAKE_TOKEN + "x")
        assert FAKE_TOKEN not in first


@pytest.mark.django_db
class TestApiResponses:
    def test_no_response_contains_a_token_shaped_string(self, auth_client, tenant_a, currencies):
        """Sweeps the Phase 1 surface; grows automatically as routes are added."""
        routes = [
            "/api/v1/auth/me/",
            "/api/v1/tenants/",
            "/api/v1/tenants/active/",
            "/api/v1/currencies/",
            "/api/v1/settings/public/",
        ]
        for route in routes:
            response = auth_client.get(route)
            assert TOKEN_SHAPE.search(response.content.decode()) is None, route

    def test_password_hash_is_never_serialized(self, auth_client, user):
        body = auth_client.get("/api/v1/auth/me/").content.decode()
        assert "password" not in body
        assert "argon2" not in body.lower()
