"""Audit writer.

Auditing must never break the operation it records: a logging failure is logged, not
raised. The exception is that we also never *silently* skip — a warning goes out.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.audit.models import ActorType, AuditLog
from apps.core.request_context import get_request_id

logger = logging.getLogger(__name__)


def _actor_type(actor) -> str:
    if actor is None:
        return ActorType.SYSTEM
    if getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False):
        return ActorType.STAFF
    return ActorType.USER


def record_audit(
    *,
    actor,
    action: str,
    resource_type: str = "",
    resource_id: str | None = "",
    tenant=None,
    ip: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    actor_type: str | None = None,
) -> AuditLog | None:
    try:
        return AuditLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            actor_type=actor_type or _actor_type(actor),
            actor_label=(getattr(actor, "email", "") or "")[:255],
            tenant=tenant,
            action=action,
            resource_type=resource_type or "",
            resource_id=(resource_id or "")[:64],
            ip=ip,
            user_agent=(user_agent or "")[:512],
            request_id=get_request_id(),
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("Failed to write audit entry for action=%s", action)
        return None
