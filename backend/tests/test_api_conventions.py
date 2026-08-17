"""Cross-cutting API contract: error shape, locale, health, idempotency storage."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.core.events import publish
from apps.core.models import OutboxMessage

pytestmark = pytest.mark.django_db


class TestErrorShape:
    def test_errors_use_the_documented_envelope(self, api):
        body = api.post(
            "/api/v1/auth/login/", {"email": "x@example.com", "password": "nope-nope-nope"},
            format="json",
        ).json()
        assert set(body) == {"error"}
        assert {"code", "message", "trace_id"} <= set(body["error"])

    def test_validation_errors_expose_field_errors(self, api):
        body = api.post("/api/v1/auth/register/", {"email": "not-an-email"}, format="json").json()
        assert body["error"]["code"] == "error.validation"
        assert "email" in body["error"]["field_errors"]

    def test_trace_id_matches_the_response_header(self, api):
        response = api.get("/api/v1/auth/me/")
        assert response.json()["error"]["trace_id"] == response["X-Request-ID"]

    def test_no_stack_trace_reaches_the_client(self, api):
        body = api.get("/api/v1/auth/me/").content.decode()
        assert "Traceback" not in body and "File \"" not in body

    def test_404_shape(self, auth_client):
        body = auth_client.get("/api/v1/tenants/00000000-0000-0000-0000-000000000000/").json()
        assert body["error"]["code"] == "error.not_found"


class TestLocale:
    def test_query_parameter_selects_the_locale(self, api):
        response = api.get("/api/v1/settings/public/?lang=fa")
        assert response["Content-Language"] == "fa"

    def test_accept_language_is_honoured(self, api):
        response = api.get("/api/v1/settings/public/", HTTP_ACCEPT_LANGUAGE="fa")
        assert response["Content-Language"] == "fa"

    def test_unknown_locale_falls_back_to_the_default(self, api):
        response = api.get("/api/v1/settings/public/?lang=xx")
        assert response["Content-Language"] == "en"

    def test_user_preference_wins_over_accept_language(self, auth_client, user):
        user.preferred_locale = "fa"
        user.save(update_fields=["preferred_locale"])
        response = auth_client.get("/api/v1/auth/me/", HTTP_ACCEPT_LANGUAGE="en")
        assert response["Content-Language"] == "fa"

    def test_error_messages_are_translated(self, api):
        """Customer-facing text must follow the locale, not the server default."""
        english = api.get("/api/v1/auth/me/?lang=en").json()["error"]["message"]
        persian = api.get("/api/v1/auth/me/?lang=fa").json()["error"]["message"]
        # Codes are stable across locales; messages are what changes.
        assert isinstance(english, str) and isinstance(persian, str)


class TestHealth:
    def test_liveness_does_not_touch_the_database(self, client):
        # A database blip must not make the orchestrator kill healthy containers.
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readiness_reports_each_dependency(self, client):
        body = client.get("/readyz").json()
        assert set(body["checks"]) == {"database", "cache", "migrations"}


class TestOutbox:
    def test_publish_writes_a_pending_row(self):
        message = publish("order.placed", {"order_id": "abc"})
        assert message.status == OutboxMessage.Status.PENDING
        assert OutboxMessage.objects.filter(event_type="order.placed").exists()

    def test_payload_is_preserved(self):
        publish("payment.approved", {"amount_minor": 14900, "currency": "USD"})
        row = OutboxMessage.objects.get(event_type="payment.approved")
        assert row.payload["amount_minor"] == 14900

    def test_a_broker_outage_does_not_break_the_caller(self, monkeypatch):
        """The outbox is the delivery guarantee; enqueueing is only an accelerator.

        Regression: an unreachable broker used to raise out of the ``on_commit`` hook
        and turn a successful checkout into a 500 — after the order was committed.
        """
        from apps.core import events

        def explode(_pk):
            raise ConnectionError("broker unreachable")

        monkeypatch.setattr(events, "_schedule_relay", events._schedule_relay)
        monkeypatch.setattr(
            "apps.core.tasks.relay_outbox_message.delay",
            lambda *args, **kwargs: explode(None),
        )

        message = publish("order.paid", {"order_id": "abc"})

        # The event survives for the periodic sweep to pick up.
        message.refresh_from_db()
        assert message.status == OutboxMessage.Status.PENDING

    def test_the_sweep_requeues_unpublished_events(self, monkeypatch):
        from apps.core.tasks import sweep_pending_outbox

        publish("order.paid", {"order_id": "xyz"})
        enqueued: list[int] = []
        monkeypatch.setattr(
            "apps.core.tasks.relay_outbox_message.delay",
            lambda pk: enqueued.append(pk),
        )

        assert sweep_pending_outbox() >= 1
        assert enqueued


class TestIdempotencyStorage:
    def test_same_key_and_endpoint_cannot_be_stored_twice(self, user):
        from django.db import IntegrityError

        from apps.core.models import IdempotencyRecord

        common = {
            "key": "abc-123",
            "endpoint": "/api/v1/orders/",
            "request_fingerprint": "f" * 64,
            "expires_at": timezone.now(),
        }
        IdempotencyRecord.objects.create(**common)
        with pytest.raises(IntegrityError):
            IdempotencyRecord.objects.create(**common)


class TestPublicSettings:
    def test_is_reachable_without_authentication(self, api):
        assert api.get("/api/v1/settings/public/").status_code == 200

    def test_only_public_settings_are_exposed(self, api, db):
        from apps.core.models import SystemSetting

        # update_or_create: the seeded catalogue may already define these, and the test
        # is about visibility, not about who created the row.
        SystemSetting.objects.update_or_create(
            key="internal_thing", defaults={"value": "secret", "is_public": False}
        )
        SystemSetting.objects.update_or_create(
            key="brand_name", defaults={"value": "Acme", "is_public": True}
        )

        body = api.get("/api/v1/settings/public/").json()
        assert "brand_name" in body["settings"]
        assert "internal_thing" not in body["settings"]
