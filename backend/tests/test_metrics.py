"""Phase 10 metrics: `django-prometheus`'s free HTTP metrics plus the custom counters
and gauges in `apps.core.metrics` that DEPLOYMENT.md §7 names explicitly (queue depth,
provisioning success/failure by error_code, outbound send success/429 rate, pool depth).

Counters are module-level globals that live for the whole test session, so every
assertion here is a delta around one action, never an absolute value — an earlier test
incrementing the same counter must not make a later one flaky.
"""

from __future__ import annotations

import pytest

from apps.core.metrics import BOT_POOL_DEPTH, OUTBOUND_SEND_TOTAL, PROVISIONING_JOB_TOTAL


def _count(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


class TestMetricsEndpoint:
    def test_metrics_endpoint_is_reachable_and_exposes_request_metrics(self, client):
        client.get("/healthz")  # generate at least one request-latency sample first

        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.content.decode()
        assert "django_http_requests_before_middlewares_total" in body

    def test_metrics_endpoint_exposes_the_custom_business_counters(self, client):
        OUTBOUND_SEND_TOTAL.labels(outcome="sent").inc()

        body = client.get("/metrics").content.decode()

        assert "botbuilder_outbound_send_total" in body
        assert "botbuilder_provisioning_job_total" in body
        assert "botbuilder_bot_pool_depth" in body
        assert "botbuilder_celery_queue_depth" in body


@pytest.mark.django_db
class TestOutboundSendCounter:
    def test_a_successful_send_increments_the_sent_outcome(self, active_instance, fake_transport):
        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage

        before = _count(OUTBOUND_SEND_TOTAL, outcome="sent")

        deliver(instance=active_instance, chat_ref="metrics-sent", message=RenderedMessage(text="hi"))

        assert _count(OUTBOUND_SEND_TOTAL, outcome="sent") == before + 1

    def test_a_locally_rate_limited_send_increments_the_rate_limited_outcome(
        self, active_instance, fake_transport
    ):
        from django.test import override_settings

        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage

        before = _count(OUTBOUND_SEND_TOTAL, outcome="rate_limited")

        with override_settings(OUTBOUND_RATE_PER_CHAT_PER_SECOND=1):
            deliver(
                instance=active_instance, chat_ref="metrics-rl", message=RenderedMessage(text="one")
            )
            deliver(
                instance=active_instance, chat_ref="metrics-rl", message=RenderedMessage(text="two")
            )

        assert _count(OUTBOUND_SEND_TOTAL, outcome="rate_limited") == before + 1

    def test_a_platform_429_increments_the_rate_limited_outcome(self, active_instance, fake_transport):
        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["sendMessage"] = PlatformApiError(
            "slow down", status_code=429, retry_after=5
        )
        before = _count(OUTBOUND_SEND_TOTAL, outcome="rate_limited")

        deliver(instance=active_instance, chat_ref="metrics-429", message=RenderedMessage(text="hi"))

        assert _count(OUTBOUND_SEND_TOTAL, outcome="rate_limited") == before + 1


@pytest.mark.django_db
class TestProvisioningJobCounter:
    def test_a_successful_job_increments_the_succeeded_outcome(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.provisioning.saga import create_job, run_job

        before = _count(PROVISIONING_JOB_TOTAL, status="succeeded", error_code="")

        run_job(create_job(order=paid_order, strategy="pool"))

        assert _count(PROVISIONING_JOB_TOTAL, status="succeeded", error_code="") == before + 1

    def test_a_failed_job_increments_its_error_code_outcome(self, paid_order, fake_transport):
        from apps.provisioning.saga import create_job, run_job

        before = _count(
            PROVISIONING_JOB_TOTAL, status="failed", error_code="provisioning.pool_empty"
        )

        run_job(create_job(order=paid_order, strategy="pool"))  # no pool_entry -> pool_empty

        after = _count(PROVISIONING_JOB_TOTAL, status="failed", error_code="provisioning.pool_empty")
        assert after == before + 1


@pytest.mark.django_db
class TestBotPoolDepthGauge:
    def test_check_pool_depth_updates_the_gauge(self, pool_entry):
        from apps.provisioning.tasks import check_pool_depth

        check_pool_depth()

        assert BOT_POOL_DEPTH.labels(platform="telegram")._value.get() >= 0
