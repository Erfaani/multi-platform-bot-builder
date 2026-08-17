"""`apps.core.celery_signals` — carries `request_id` from the process that enqueues a
task into the worker process that runs it. Verified live against a real worker once while
building this (a dispatched task's log line showed the exact `request_id` set before
`.delay()`, through the real Redis broker) — these tests exercise the same signal handlers
directly, without a live broker, so they run in CI on every change."""

from __future__ import annotations

from apps.core.celery_signals import _clear_request_id, _restore_request_id, _stash_request_id
from apps.core.request_context import get_request_id, set_request_id


class _FakeRequest:
    def __init__(self, request_id: str | None) -> None:
        if request_id is not None:
            self.request_id = request_id


class _FakeTask:
    def __init__(self, request) -> None:
        self.request = request


class TestStashOnPublish:
    def test_the_current_request_id_is_written_into_the_outgoing_headers(self):
        set_request_id("abc123")
        headers: dict = {}

        _stash_request_id(headers=headers)

        assert headers["request_id"] == "abc123"

    def test_a_none_headers_dict_is_tolerated(self):
        set_request_id("abc123")
        _stash_request_id(headers=None)  # must not raise


class TestRestoreOnWorker:
    def test_a_task_carrying_a_request_id_restores_it(self):
        _restore_request_id(task=_FakeTask(_FakeRequest("carried-along")))
        assert get_request_id() == "carried-along"

    def test_a_task_with_no_request_id_gets_a_fresh_one_not_the_previous_tasks(self):
        set_request_id("stale-from-a-previous-task")

        _restore_request_id(task=_FakeTask(_FakeRequest(None)))

        assert get_request_id() != "stale-from-a-previous-task"
        assert get_request_id() != "-"

    def test_a_missing_task_still_sets_something(self):
        _restore_request_id(task=None)
        assert get_request_id() != "-"


class TestClearAfterRun:
    def test_clearing_resets_to_the_default(self):
        set_request_id("leftover")
        _clear_request_id()
        assert get_request_id() == "-"
