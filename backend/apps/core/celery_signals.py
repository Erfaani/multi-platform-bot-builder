"""Carries `request_id` from the request that enqueued a task into the worker process
that runs it (Phase 10) — the other half of `apps.core.request_context`'s stated intent
("propagated to logs and Celery"), which until now only did the "logs" part.

Celery's own message headers are the mechanism: `before_task_publish` (fires on the
*publishing* side — inside the request, before `.delay()`/`.apply_async()` actually sends
the message) stashes the current `request_id` into the outgoing message's headers;
`task_prerun` (fires on the *worker* side, just before the task body runs) reads it back
out and sets the worker process's own contextvar, so every log line the task emits — via
the same `apps.core.logging` JSON pipeline the web process uses — carries the same
`request_id` a support engineer already has from the API response that triggered it.
`task_postrun` clears it again, for the same pooled-worker-process reason
`apps.core.tenant_session` resets its own state after every web request: a worker process
handles many tasks in sequence, and nothing else would stop one task's id leaking into the
next task that happens to run in the same process.

A task run outside of any request (the Celery beat scheduler, a management command calling
`.delay()` directly) simply gets a fresh id of its own — `task_prerun` always sets
*something*, never leaves the worker logging under the id of a previous, unrelated task.

This module also logs terminal task failures to `FailedTaskLog` (Phase 10's DLQ): Celery
fires `task_failure` only once a task is done retrying, so one row here means one task
genuinely died, not one retry attempt among several.
"""

from __future__ import annotations

import logging

from celery.signals import task_failure, task_postrun, task_prerun
from celery.signals import before_task_publish

from apps.core.request_context import get_request_id, new_request_id, set_request_id

logger = logging.getLogger(__name__)


def _stash_request_id(sender=None, headers=None, **kwargs) -> None:
    if headers is not None:
        headers["request_id"] = get_request_id()


def _restore_request_id(sender=None, task=None, **kwargs) -> None:
    request_id = ""
    request = getattr(task, "request", None) if task is not None else None
    if request is not None:
        request_id = getattr(request, "request_id", "") or ""
        if not request_id and hasattr(request, "get"):
            request_id = request.get("request_id", "") or ""
    set_request_id(request_id or new_request_id())


def _clear_request_id(sender=None, **kwargs) -> None:
    set_request_id("-")


def _redact_value(value):
    from apps.core.logging import redact

    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def _log_task_failure(
    sender=None,
    task_id=None,
    exception=None,
    args=None,
    kwargs=None,
    traceback=None,
    einfo=None,
    **extra,
) -> None:
    from apps.core.logging import redact
    from apps.core.models import FailedTaskLog

    task_name = getattr(sender, "name", None) or type(sender).__name__

    try:
        FailedTaskLog.objects.create(
            task_name=task_name,
            task_id=task_id or "",
            args=_redact_value(list(args)) if args else [],
            kwargs=_redact_value(dict(kwargs)) if kwargs else {},
            exception_type=type(exception).__name__ if exception is not None else "",
            exception_message=redact(str(exception))[:2000] if exception is not None else "",
            traceback=redact(str(einfo))[:10000] if einfo is not None else "",
            request_id=get_request_id(),
        )
    except Exception:
        # The DB being unavailable is a plausible *cause* of the task failure this is
        # trying to record — must never let recording it raise a second exception.
        logger.error("Could not write FailedTaskLog for task %s", task_name, exc_info=True)


def register() -> None:
    before_task_publish.connect(_stash_request_id, dispatch_uid="celery_signals.stash_request_id")
    task_prerun.connect(_restore_request_id, dispatch_uid="celery_signals.restore_request_id")
    task_postrun.connect(_clear_request_id, dispatch_uid="celery_signals.clear_request_id")
    task_failure.connect(_log_task_failure, dispatch_uid="celery_signals.log_task_failure")
