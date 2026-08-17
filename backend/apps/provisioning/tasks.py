"""Provisioning background tasks.

Triggered by the `order.paid` domain event. At-least-once delivery means these must be
idempotent — `create_job` is keyed on the order, and `run_job` resumes rather than
replays.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.provisioning.models import JobStatus, ProvisioningJob
from apps.provisioning.saga import create_job, run_job

logger = logging.getLogger(__name__)

#: apps/provisioning/tasks.py:check_pool_depth — see CELERY_BEAT_SCHEDULE.
CHECK_POOL_DEPTH_INTERVAL_SECONDS = 1800


@shared_task
def provision_order(order_public_id: str) -> str:
    """Not retried at the Celery level by design: `run_job` already absorbs every
    exception into `ProvisioningJob.status=FAILED` + a closed `error_code`, and staff
    retry a failed job through `resume_job`, not through this task raising again. A
    `max_retries` here would only race that domain-level mechanism, not replace it."""
    from apps.orders.models import Order

    order = Order.objects.filter(public_id=order_public_id).first()
    if order is None:
        logger.warning("Provisioning asked for unknown order %s", order_public_id)
        return "missing"

    job = create_job(order=order)
    if job.status in {JobStatus.SUCCEEDED, JobStatus.RUNNING}:
        return job.status

    job = run_job(job)
    return job.status


@shared_task
def resume_job(job_public_id: str) -> str:
    """Continue a job that was waiting on the customer, or retry a failed one."""
    job = ProvisioningJob.objects.filter(public_id=job_public_id).first()
    if job is None:
        return "missing"
    if not job.is_resumable:
        return job.status
    return run_job(job).status


@shared_task
def check_pool_depth() -> dict:
    """Warn operations before the pool runs dry.

    An empty pool turns an "instant" order into a stalled one, so this needs to be
    noticed before a customer does.
    """
    from django.conf import settings

    from apps.bots.credentials import pool_depth
    from apps.core.metrics import BOT_POOL_DEPTH
    from apps.platforms.constants import SELLABLE_PLATFORMS

    depths = {platform: pool_depth(platform) for platform in SELLABLE_PLATFORMS}
    for platform, depth in depths.items():
        BOT_POOL_DEPTH.labels(platform=platform).set(depth)
        if depth < settings.BOT_POOL_LOW_WATERMARK:
            logger.warning(
                "Bot pool for %s is low: %s available (watermark %s)",
                platform,
                depth,
                settings.BOT_POOL_LOW_WATERMARK,
            )
    return depths
