"""Per-request context, propagated to logs and Celery.

A ContextVar rather than thread-locals so it survives async views.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_tenant: ContextVar[Any] = ContextVar("active_tenant", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


def set_active_tenant(tenant: Any) -> None:
    _tenant.set(tenant)


def get_active_tenant() -> Any:
    return _tenant.get()
