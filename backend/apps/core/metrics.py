"""Custom Prometheus metrics (Phase 10).

`django-prometheus` (wired in `MIDDLEWARE`) already covers request latency and count
by view/method for free — that alone covers two items from DEPLOYMENT.md §7's list
("metrics for request latency, ... webhook ingress latency"): the webhook view is a
normal Django view like any other, so its latency is already exported with no extra
code here.

This module covers the rest of that list — the metrics that need either a counter at
the moment something happens (outbound sends, provisioning outcomes — Prometheus
Counters, not something a scrape-time DB query could reconstruct after the fact) or a
live read of state a scrape-time query, not a counter, is the only accurate answer for
(pool depth, Celery queue depth).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

#: `outcome` is a small, fixed enum on purpose — labeling by the raw error text (as
#: `_retry_or_fail`'s `reason` argument is, for one branch) would be unbounded
#: cardinality, which is the one Prometheus mistake that actually breaks a server.
OUTBOUND_SEND_TOTAL = Counter(
    "botbuilder_outbound_send_total",
    "Outbound platform message attempts, by final outcome for this attempt.",
    ["outcome"],
)

#: `error_code` is safe to label by because it is the same closed, enumerable set
#: `apps.provisioning.saga.PROVISIONING_ERROR_CODES` already guarantees for
#: `ProvisioningJob.error_code` — not free text.
PROVISIONING_JOB_TOTAL = Counter(
    "botbuilder_provisioning_job_total",
    "Provisioning jobs that reached a terminal state, by outcome.",
    ["status", "error_code"],
)

BOT_POOL_DEPTH = Gauge(
    "botbuilder_bot_pool_depth",
    "Pooled, unassigned bot credentials currently available, by platform.",
    ["platform"],
)


def _queue_depths() -> dict[str, int]:
    """A broker outage must never hang a `/metrics` scrape — Prometheus would keep
    retrying against a worker thread that never frees up. Both timeouts are set
    explicitly: `redis-py` does not time out DNS/connect/read by default."""
    from django.conf import settings

    queues = ("default", "telegram", "bale")
    try:
        import redis

        client = redis.from_url(
            settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1
        )
        return {queue: client.llen(queue) for queue in queues}
    except Exception:
        return {}


class _QueueDepthCollector:
    """Celery queue length, read from the Redis broker at scrape time.

    Current state, not a counted event, so a live `LLEN` at scrape time is the
    correct source of truth — unlike the Counters above, there is no call site to
    instrument; Redis already tracks this for free.
    """

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        family = GaugeMetricFamily(
            "botbuilder_celery_queue_depth",
            "Pending messages waiting in each Celery queue.",
            labels=["queue"],
        )
        for queue, depth in _queue_depths().items():
            family.add_metric([queue], depth)
        return [family]


def register_queue_depth_collector() -> None:
    """Called once from `apps.core.apps.CoreConfig.ready()`."""
    from prometheus_client import REGISTRY

    try:
        REGISTRY.register(_QueueDepthCollector())
    except ValueError:
        pass  # already registered — `ready()` can run more than once under some runners
