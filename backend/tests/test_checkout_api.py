"""Checkout through the API: quote → order → payment → proof → review."""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import StaffRole, User, UserStaffRole
from apps.payments.models import PaymentMethod, PaymentMethodKind

pytestmark = pytest.mark.django_db


def receipt(name: str = "receipt.png") -> SimpleUploadedFile:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def card_method(catalogue, db) -> PaymentMethod:
    return PaymentMethod.objects.create(
        name="Test card",
        kind=PaymentMethodKind.MANUAL_CARD,
        provider_slug="manual_card",
        currency="USD",
        config={"card_number": "6037-9999-0000-1111", "card_holder": "Platform", "bank_name": "Melli"},
        is_enabled=True,
    )


@pytest.fixture
def finance_client(db):
    from rest_framework.test import APIClient

    from apps.accounts.services import issue_tokens

    agent = User.objects.create_user(email="fin-api@example.com", password="TestPassw0rd!23")
    UserStaffRole.objects.create(user=agent, role=StaffRole.FINANCE_AGENT)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(agent)['access']}")
    return client, agent


def ordered(api, auth_client, tenant_a) -> dict:
    """Build a quote anonymously, claim it, and place the order."""
    quote = api.post(
        "/api/v1/quotes/",
        {
            "template": "clinic",
            "platforms": ["telegram"],
            "features": ["faq"],
            "currency": "USD",
            "business": {"name": "API Clinic"},
        },
        format="json",
    ).json()

    auth_client.post(
        f"/api/v1/quotes/{quote['id']}/claim/",
        HTTP_X_QUOTE_SESSION=quote["session_secret"],
    )
    response = auth_client.post("/api/v1/orders/", {"quote": quote["id"]}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


class TestPlacingAnOrder:
    def test_a_claimed_quote_becomes_an_order(self, api, auth_client, catalogue, tenant_a):
        order = ordered(api, auth_client, tenant_a)
        assert order["status"] == "PENDING_PAYMENT"
        assert order["number"] >= 10_000
        assert order["items"]

    def test_the_order_total_matches_the_quote(self, api, auth_client, catalogue, tenant_a):
        quote = api.post(
            "/api/v1/quotes/",
            {"template": "clinic", "platforms": ["telegram"], "features": ["faq"], "currency": "USD"},
            format="json",
        ).json()
        auth_client.post(
            f"/api/v1/quotes/{quote['id']}/claim/", HTTP_X_QUOTE_SESSION=quote["session_secret"]
        )
        order = auth_client.post(
            "/api/v1/orders/", {"quote": quote["id"]}, format="json"
        ).json()

        assert order["total"]["amount_minor"] == quote["total"]["amount_minor"]

    def test_an_unclaimed_quote_cannot_be_ordered(self, api, auth_client, catalogue, tenant_a):
        quote = api.post(
            "/api/v1/quotes/",
            {"template": "clinic", "platforms": ["telegram"], "features": [], "currency": "USD"},
            format="json",
        ).json()

        response = auth_client.post("/api/v1/orders/", {"quote": quote["id"]}, format="json")
        assert response.status_code == 404

    def test_ordering_requires_authentication(self, api, catalogue):
        assert api.post("/api/v1/orders/", {"quote": str(__import__("uuid").uuid4())}, format="json").status_code == 401

    def test_available_actions_come_from_the_state_machine(
        self, api, auth_client, catalogue, tenant_a
    ):
        order = ordered(api, auth_client, tenant_a)
        assert "CANCELLED" in order["available_actions"]
        assert "RECEIPT_SUBMITTED" in order["available_actions"]
        # A customer can never move their own order to PAID.
        assert "PAID" not in order["available_actions"]


class TestTenantIsolation:
    def test_orders_are_scoped_to_the_workspace(
        self, api, auth_client, other_client, catalogue, tenant_a, tenant_b
    ):
        ordered(api, auth_client, tenant_a)

        mine = auth_client.get("/api/v1/orders/").json()
        theirs = other_client.get("/api/v1/orders/").json()

        assert mine["count"] == 1
        assert theirs["count"] == 0

    def test_another_tenants_order_returns_404(
        self, api, auth_client, other_client, catalogue, tenant_a, tenant_b
    ):
        order = ordered(api, auth_client, tenant_a)
        assert other_client.get(f"/api/v1/orders/{order['id']}/").status_code == 404

    def test_another_tenant_cannot_cancel_it(
        self, api, auth_client, other_client, catalogue, tenant_a, tenant_b
    ):
        order = ordered(api, auth_client, tenant_a)
        response = other_client.post(f"/api/v1/orders/{order['id']}/cancel/", {}, format="json")
        assert response.status_code == 404


class TestPaymentFlow:
    def test_the_customer_sees_only_matching_payment_methods(
        self, api, auth_client, catalogue, tenant_a, card_method
    ):
        order = ordered(api, auth_client, tenant_a)
        methods = auth_client.get(
            f"/api/v1/orders/{order['id']}/payment-methods/"
        ).json()

        assert [m["name"] for m in methods] == ["Test card"]

    def test_starting_a_payment_returns_the_card_details(
        self, api, auth_client, catalogue, tenant_a, card_method
    ):
        order = ordered(api, auth_client, tenant_a)
        payment = auth_client.post(
            "/api/v1/payments/",
            {"order": order["id"], "payment_method": str(card_method.public_id)},
            format="json",
        ).json()

        assert payment["status"] == "PENDING"
        assert payment["instructions"]["copyable"] == "6037-9999-0000-1111"
        assert payment["proof"]["requires_file"] is True

    def test_uploading_a_receipt_moves_the_order_to_review(
        self, api, auth_client, catalogue, tenant_a, card_method
    ):
        order = ordered(api, auth_client, tenant_a)
        payment = auth_client.post(
            "/api/v1/payments/",
            {"order": order["id"], "payment_method": str(card_method.public_id)},
            format="json",
        ).json()

        response = auth_client.post(
            f"/api/v1/payments/{payment['id']}/proof/",
            {"file": receipt()},
            format="multipart",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "RECEIPT_SUBMITTED"

        refreshed = auth_client.get(f"/api/v1/orders/{order['id']}/").json()
        assert refreshed["status"] == "RECEIPT_SUBMITTED"

    def test_a_malicious_upload_is_rejected(
        self, api, auth_client, catalogue, tenant_a, card_method
    ):
        order = ordered(api, auth_client, tenant_a)
        payment = auth_client.post(
            "/api/v1/payments/",
            {"order": order["id"], "payment_method": str(card_method.public_id)},
            format="json",
        ).json()

        evil = SimpleUploadedFile(
            "receipt.png", b"<script>alert(1)</script>", content_type="image/png"
        )
        response = auth_client.post(
            f"/api/v1/payments/{payment['id']}/proof/", {"file": evil}, format="multipart"
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"].startswith("upload.")

    def test_another_tenant_cannot_read_the_payment(
        self, api, auth_client, other_client, catalogue, tenant_a, tenant_b, card_method
    ):
        order = ordered(api, auth_client, tenant_a)
        payment = auth_client.post(
            "/api/v1/payments/",
            {"order": order["id"], "payment_method": str(card_method.public_id)},
            format="json",
        ).json()

        assert other_client.get(f"/api/v1/payments/{payment['id']}/").status_code == 404

    def test_the_internal_note_is_never_exposed(
        self, api, auth_client, catalogue, tenant_a, card_method
    ):
        """Staff notes about a customer must not reach that customer."""
        order = ordered(api, auth_client, tenant_a)
        payment = auth_client.post(
            "/api/v1/payments/",
            {"order": order["id"], "payment_method": str(card_method.public_id)},
            format="json",
        ).json()

        assert "internal_note" not in payment

    def test_the_customer_cannot_pay_a_cancelled_order(
        self, api, auth_client, catalogue, tenant_a, card_method
    ):
        order = ordered(api, auth_client, tenant_a)
        auth_client.post(f"/api/v1/orders/{order['id']}/cancel/", {}, format="json")

        response = auth_client.post(
            "/api/v1/payments/",
            {"order": order["id"], "payment_method": str(card_method.public_id)},
            format="json",
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "payment.order_not_payable"


class TestNotificationsApi:
    def test_the_customer_can_read_their_notifications(
        self, api, auth_client, catalogue, tenant_a, user, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            ordered(api, auth_client, tenant_a)

        body = auth_client.get("/api/v1/notifications/").json()
        assert body["count"] >= 1
        assert body["results"][0]["title"]

    def test_notifications_are_localised_at_read_time(
        self, api, auth_client, catalogue, tenant_a, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            ordered(api, auth_client, tenant_a)

        english = auth_client.get("/api/v1/notifications/?lang=en").json()["results"][0]
        persian = auth_client.get("/api/v1/notifications/?lang=fa").json()["results"][0]
        assert english["title"] != persian["title"]

    def test_a_user_cannot_read_someone_elses_notifications(
        self, api, auth_client, other_client, catalogue, tenant_a, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            ordered(api, auth_client, tenant_a)

        assert other_client.get("/api/v1/notifications/").json()["count"] == 0

    def test_marking_read_updates_the_unread_count(
        self, api, auth_client, catalogue, tenant_a, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            ordered(api, auth_client, tenant_a)

        before = auth_client.get("/api/v1/notifications/unread-count/").json()["unread"]
        first = auth_client.get("/api/v1/notifications/").json()["results"][0]
        auth_client.post(f"/api/v1/notifications/{first['id']}/read/")

        after = auth_client.get("/api/v1/notifications/unread-count/").json()["unread"]
        assert after == before - 1
