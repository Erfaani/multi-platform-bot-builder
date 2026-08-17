"""Structured JSON logging (Phase 10) — both the stdlib `logging.getLogger()` calls used
throughout this codebase and native `structlog.get_logger()` calls must converge on the
same, single JSON pipeline, and the existing secret redaction must still apply once it
does."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from apps.core.logging import SecretRedactingFilter, build_json_formatter


@pytest.fixture
def json_handler():
    """A standalone handler+formatter pair, independent of `LOGGING`'s real console
    handler — isolates the assertion to "does the formatter itself produce correct
    JSON", not "is stdout currently JSON" (which depends on `LOG_FORMAT`). Carries the
    real `SecretRedactingFilter` (not a stand-in) since one test below depends on it
    actually running."""
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_json_formatter())
    handler.addFilter(SecretRedactingFilter())
    yield stream, handler


def _configure(logger_name: str, handler: logging.Handler) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


class TestJSONFormatter:
    def test_a_plain_stdlib_log_call_renders_as_valid_json(self, json_handler):
        stream, handler = json_handler
        logger = _configure("test.stdlib.plain", handler)

        logger.info("hello there")

        payload = json.loads(stream.getvalue().strip())
        assert payload["event"] == "hello there"
        assert payload["level"] == "info"
        assert payload["logger"] == "test.stdlib.plain"
        assert "timestamp" in payload
        assert "request_id" in payload

    def test_an_exception_carries_the_traceback(self, json_handler):
        stream, handler = json_handler
        logger = _configure("test.stdlib.exc", handler)

        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("it broke")

        payload = json.loads(stream.getvalue().strip())
        assert payload["event"] == "it broke"
        assert "ValueError: boom" in payload["exception"]

    def test_a_bot_token_shaped_string_is_still_redacted(self, json_handler):
        stream, handler = json_handler
        logger = _configure("test.stdlib.redact", handler)

        logger.info("token was 123456789:AAdummyLookingTokenLongEnoughToMatch1234567890")

        payload = json.loads(stream.getvalue().strip())
        assert "[REDACTED]" in payload["event"]
        assert "AAdummyLooking" not in payload["event"]

    def test_a_native_structlog_call_carries_its_bound_fields(self, json_handler):
        stream, handler = json_handler
        _configure("test.structlog", handler)

        structlog.get_logger("test.structlog").info("order placed", order_id=42, amount_minor=1500)

        payload = json.loads(stream.getvalue().strip())
        assert payload["event"] == "order placed"
        assert payload["order_id"] == 42
        assert payload["amount_minor"] == 1500

    def test_a_real_request_gets_a_request_id_of_the_expected_shape(self, auth_client):
        """`apps.core.middleware.RequestIDMiddleware` is what actually populates the
        contextvar `_bind_request_context` reads — this proves that middleware still
        runs and produces an id in `new_request_id()`'s shape (16 lowercase hex chars),
        end to end through the real middleware stack, not just at the formatter level."""
        response = auth_client.get("/api/v1/auth/me/")
        assert response.status_code == 200
        request_id = response["X-Request-ID"]
        assert len(request_id) == 16
        int(request_id, 16)  # raises ValueError if it isn't hex
