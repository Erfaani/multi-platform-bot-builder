"""Phase 10 job retry/DLQ policy.

Three things this covers:

1. Tasks whose failures are already fully absorbed into a domain status field
   (`provision_order` -> `ProvisioningJob.error_code`, `scan_receipt` -> nothing can
   fail yet) declare no Celery-level retry budget — one was never real, since nothing
   inside either ever calls `self.retry()`.
2. Tasks with a genuine transient-infra failure surface that nothing else sweeps up
   (`deliver_notification`, `process_update`) declare a narrow `autoretry_for` on the
   specific transient exception types, not a blanket catch-all.
3. `FailedTaskLog` (`apps.core.celery_signals._log_task_failure`) is Celery's own DLQ:
   a durable, operator-visible row for any task that fails for good, independent of
   whatever domain-specific tracking that task already has for itself.
"""

from __future__ import annotations

import pytest
from django.db.utils import OperationalError
from django_redis.exceptions import ConnectionInterrupted

from apps.bot_runtime.tasks import process_update
from apps.core.celery_signals import _log_task_failure
from apps.core.models import FailedTaskLog
from apps.notifications.tasks import deliver_notification
from apps.payments.tasks import scan_receipt
from apps.provisioning.tasks import provision_order


class TestDeadRetryConfigWasRemoved:
    def test_provision_order_declares_no_autoretry(self):
        assert getattr(provision_order, "autoretry_for", ()) == ()

    def test_provision_order_is_not_bound_to_self(self):
        # `bind=True` with an unused `self` was the original bug: kept, it would let
        # someone believe `self.retry()` was available inside when nothing calls it.
        import inspect

        params = list(inspect.signature(provision_order.run).parameters)
        assert "self" not in params

    def test_scan_receipt_declares_no_autoretry(self):
        assert getattr(scan_receipt, "autoretry_for", ()) == ()

    def test_scan_receipt_is_not_bound_to_self(self):
        import inspect

        params = list(inspect.signature(scan_receipt.run).parameters)
        assert "self" not in params

    @pytest.mark.django_db
    def test_provision_order_still_runs_end_to_end_for_an_unknown_order(self):
        assert provision_order("00000000-0000-0000-0000-000000000000") == "missing"

    @pytest.mark.django_db
    def test_scan_receipt_still_runs_end_to_end_for_an_unknown_receipt(self):
        assert scan_receipt(999_999_999) == "missing"


class TestTransientFailureRetryIsScoped:
    def test_deliver_notification_only_retries_on_a_database_blip(self):
        assert deliver_notification.autoretry_for == (OperationalError,)
        assert deliver_notification.max_retries == 3

    def test_process_update_retries_on_database_or_session_store_blips(self):
        assert process_update.autoretry_for == (OperationalError, ConnectionInterrupted)
        assert process_update.max_retries == 3


class _FakeSender:
    name = "apps.fake.tasks.fake_task"


@pytest.mark.django_db
class TestFailedTaskLog:
    def test_a_terminal_failure_is_recorded(self):
        _log_task_failure(
            sender=_FakeSender(),
            task_id="task-abc-123",
            exception=ValueError("boom"),
            args=[1, "two"],
            kwargs={"three": 3},
            einfo="Traceback (most recent call last):\n  ...\nValueError: boom",
        )

        entry = FailedTaskLog.objects.get()
        assert entry.task_name == "apps.fake.tasks.fake_task"
        assert entry.task_id == "task-abc-123"
        assert entry.args == [1, "two"]
        assert entry.kwargs == {"three": 3}
        assert entry.exception_type == "ValueError"
        assert "boom" in entry.exception_message
        assert "ValueError: boom" in entry.traceback

    def test_secrets_in_task_arguments_are_redacted(self):
        _log_task_failure(
            sender=_FakeSender(),
            task_id="task-secret",
            exception=RuntimeError("token=abcdef0123456789abcdef0123456789 was rejected"),
            args=["123456789:AAdummyLookingTokenLongEnoughToMatch1234567890"],
            kwargs={},
            einfo="",
        )

        entry = FailedTaskLog.objects.get(task_id="task-secret")
        assert "[REDACTED]" in entry.args[0]
        assert "AAdummyLooking" not in entry.args[0]
        assert "[REDACTED]" in entry.exception_message

    def test_a_missing_database_while_logging_the_failure_does_not_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise OperationalError("connection refused")

        monkeypatch.setattr(FailedTaskLog.objects, "create", _boom)

        _log_task_failure(sender=_FakeSender(), task_id="x", exception=ValueError("y"))  # must not raise


class TestBeatScheduleCoversTheSweepTasks:
    """Each of these existed as a task, with a docstring describing it as periodic, long
    before it was ever entered into `CELERY_BEAT_SCHEDULE` — meaning none of them had
    ever actually run outside a test or a manual shell call. `outbound-retry` was the
    sharpest gap: the only thing that ever re-attempts a rate-limited outbound message."""

    def test_every_previously_orphaned_sweep_task_is_now_scheduled(self):
        from django.conf import settings

        scheduled_tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}

        assert "apps.core.tasks.sweep_pending_outbox" in scheduled_tasks
        assert "apps.core.tasks.purge_expired_idempotency_records" in scheduled_tasks
        assert "apps.provisioning.tasks.check_pool_depth" in scheduled_tasks
        assert "apps.bot_runtime.tasks.sweep_pending_updates" in scheduled_tasks
        assert "apps.bot_runtime.tasks.retry_outbound" in scheduled_tasks
        assert "apps.bot_runtime.tasks.purge_expired_sessions" in scheduled_tasks

    def test_every_schedule_entry_names_a_real_importable_task(self):
        from django.conf import settings
        from django.utils.module_loading import import_string

        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            assert import_string(entry["task"]) is not None, (
                f"{name} points at a task that does not exist"
            )
