"""Celery application.

Queues are split per platform on purpose: `telegram` and `bale` may run on hosts with
different network egress. See docs/00-ANALYSIS.md R-03.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("botbuilder")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Tasks are at-least-once: every task must be idempotent by key.
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_default_queue="default",
    # Celery installs its own root-logger handlers/formatters by default, silently
    # discarding Django's `LOGGING` config (the JSON formatter, the request-id filter,
    # the secret redaction) for every worker process. `apps.core.celery_signals` exists
    # specifically to carry `request_id` into worker logs — this is what lets that
    # actually reach a handler that renders it (Phase 10).
    worker_hijack_root_logger=False,
    # Nothing in this system reads a task result — work is recorded in the database,
    # not in the result backend. Leaving results on makes every `.delay()` contact the
    # backend first, so a degraded Redis stalls the *calling web request* for over a
    # minute of retries before giving up. Durability comes from the outbox, not here.
    task_ignore_result=True,
    task_routes={
        "apps.platforms.telegram.*": {"queue": "telegram"},
        "apps.platforms.bale.*": {"queue": "bale"},
    },
)


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - operational helper
    return f"request: {self.request!r}"
