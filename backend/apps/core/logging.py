"""Logging filters, and (Phase 10) structured JSON output.

The redaction filter is a safety net, not a licence: bot tokens must never be passed
to a logger in the first place (SECURITY.md §5).
"""

from __future__ import annotations

import logging
import re

import structlog

# Telegram/Bale bot token shape: <numeric id>:<35+ url-safe chars>
_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{20,}", re.IGNORECASE)
_KEYVALUE_RE = re.compile(
    r"((?:token|secret|password|api[_-]?key|kek)\"?\s*[:=]\s*\"?)([^\s\",}]{6,})",
    re.IGNORECASE,
)

REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    text = _TOKEN_RE.sub(REDACTED, text)
    text = _BEARER_RE.sub(rf"\1{REDACTED}", text)
    return _KEYVALUE_RE.sub(rf"\1{REDACTED}", text)


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact(arg) if isinstance(arg, str) else arg for arg in record.args
                )
        return True


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from apps.core.request_context import get_request_id

        record.request_id = get_request_id()
        return True


# --------------------------------------------------------------------------- structured JSON

#: Shared by both pipelines below: native `structlog.get_logger()` calls, and every plain
#: `logging.getLogger(__name__)` call already used throughout this codebase — the two only
#: converge at `ProcessorFormatter`, so each needs its own copy of this processor.
def _bind_request_context(logger, method_name, event_dict):
    from apps.core.request_context import get_active_tenant, get_request_id

    event_dict["request_id"] = get_request_id()
    tenant = get_active_tenant()
    if tenant is not None:
        event_dict["tenant_id"] = str(getattr(tenant, "public_id", tenant))
    return event_dict


def build_json_formatter() -> structlog.stdlib.ProcessorFormatter:
    """The formatter `LOGGING["formatters"]["json"]` (`config/settings/base.py`) wires up.

    A zero-arg factory (referenced via dictConfig's `"()"` key) because
    `ProcessorFormatter` needs constructor arguments a plain `format` string can't
    express. `foreign_pre_chain` is what makes this apply uniformly to stdlib
    `logging.getLogger(...).info(...)` calls — nearly everything in this codebase — not
    only to code that calls `structlog.get_logger()` directly.
    """
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            _bind_request_context,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ],
    )


def configure_structlog() -> None:
    """Called once from `config/settings/base.py`. Makes `structlog.get_logger()` usable
    anywhere in the codebase, its output routed through the same stdlib handlers (and
    therefore the same `SecretRedactingFilter` and JSON/plain formatter) as everything
    else — there is exactly one logging pipeline, not two."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _bind_request_context,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
