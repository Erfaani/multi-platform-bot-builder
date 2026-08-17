"""Orders and manual payments, end to end through the service layer."""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import StaffRole, User, UserStaffRole
from apps.core.errors import ConflictError, PermissionDeniedError, ValidationError
from apps.notifications.models import Notification
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.models import Order, OrderEvent
from apps.orders.services import build_quote, claim_quote, place_order, transition_order
from apps.payments.models import Payment, PaymentMethod, PaymentMethodKind, PaymentStatus
from apps.payments.services import (
    approve_payment,
    available_methods,
    begin_review,
    reject_payment,
    start_payment,
    submit_proof,
)

pytestmark = pytest.mark.django_db


def png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def receipt_file(name: str = "receipt.png", colour: str = "red") -> SimpleUploadedFile:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def card_method(catalogue, db) -> PaymentMethod:
    return PaymentMethod.objects.create(
        name="Test card",
        kind=PaymentMethodKind.MANUAL_CARD,
        provider_slug="manual_card",
        currency="USD",
        config={"card_number": "1234", "card_holder": "Platform", "bank_name": "Bank"},
        is_enabled=True,
    )


@pytest.fixture
def crypto_method(catalogue, db) -> PaymentMethod:
    return PaymentMethod.objects.create(
        name="USDT TRC20",
        kind=PaymentMethodKind.MANUAL_CRYPTO,
        provider_slug="manual_crypto",
        currency="USD",
        network="TRC20",
        config={"wallet_address": "TXyz123"},
        is_enabled=True,
    )


@pytest.fixture
def finance(db) -> User:
    agent = User.objects.create_user(email="finance@example.com", password="TestPassw0rd!23")
    UserStaffRole.objects.create(user=agent, role=StaffRole.FINANCE_AGENT)
    return agent


@pytest.fixture
def support(db) -> User:
    agent = User.objects.create_user(email="support2@example.com", password="TestPassw0rd!23")
    UserStaffRole.objects.create(user=agent, role=StaffRole.SUPPORT_AGENT)
    return agent


def make_order(tenant, user, features=("faq",)) -> Order:
    quote, _ = build_quote(
        template_slug="clinic",
        platforms=["telegram"],
        feature_slugs=list(features),
        currency="USD",
        business_draft={"name": "Test Clinic"},
    )
    claim_quote(quote=quote, tenant=tenant, user=user)
    return place_order(quote=quote, tenant=tenant, user=user)


class TestPlacingAnOrder:
    def test_a_quote_becomes_an_order_awaiting_payment(self, catalogue, tenant_a, user):
        order = make_order(tenant_a, user)
        assert order.status == OrderStatus.PENDING_PAYMENT.value
        assert order.number >= 10_000

    def test_the_order_copies_the_quoted_lines_verbatim(self, catalogue, tenant_a, user):
        order = make_order(tenant_a, user)
        quote = order.quote
        assert order.total_minor == quote.total_minor
        assert order.items.count() == quote.items.count()

    def test_order_numbers_are_unique_and_sequential(self, catalogue, tenant_a, user):
        first = make_order(tenant_a, user)
        second = make_order(tenant_a, user)
        assert second.number > first.number

    def test_placing_the_same_quote_twice_returns_the_same_order(
        self, catalogue, tenant_a, user
    ):
        """A double-clicked checkout button must not create two orders."""
        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram"], feature_slugs=[], currency="USD"
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)

        first = place_order(quote=quote, tenant=tenant_a, user=user)
        second = place_order(quote=quote, tenant=tenant_a, user=user)
        assert first.pk == second.pk
        assert Order.objects.filter(tenant=tenant_a).count() == 1

    def test_an_expired_quote_cannot_be_ordered(self, catalogue, tenant_a, user):
        from apps.orders.models import Quote

        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram"], feature_slugs=[], currency="USD"
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        Quote.objects.filter(pk=quote.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        quote.refresh_from_db()

        with pytest.raises(ConflictError):
            place_order(quote=quote, tenant=tenant_a, user=user)

    def test_another_tenants_quote_cannot_be_ordered(
        self, catalogue, tenant_a, tenant_b, user, other_user
    ):
        from apps.core.errors import NotFoundError

        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram"], feature_slugs=[], currency="USD"
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)

        with pytest.raises(NotFoundError):
            place_order(quote=quote, tenant=tenant_b, user=other_user)

    def test_placing_an_order_records_an_event(self, catalogue, tenant_a, user):
        order = make_order(tenant_a, user)
        assert OrderEvent.objects.filter(
            order=order, to_status=OrderStatus.PENDING_PAYMENT.value
        ).exists()


class TestPaymentMethodSelection:
    def test_only_matching_currencies_are_offered(self, catalogue, card_method):
        assert card_method in available_methods(currency="USD")
        assert card_method not in available_methods(currency="IRR")

    def test_a_currency_mismatch_is_refused(self, catalogue, tenant_a, user, card_method):
        order = make_order(tenant_a, user)
        card_method.currency = "IRR"
        card_method.save(update_fields=["currency"])

        with pytest.raises(ValidationError) as exc:
            start_payment(order=order, method=card_method, user=user)
        assert exc.value.code == "payment.currency_mismatch"

    def test_a_disabled_method_is_refused(self, catalogue, tenant_a, user, card_method):
        order = make_order(tenant_a, user)
        card_method.is_enabled = False
        card_method.save(update_fields=["is_enabled"])

        with pytest.raises(ValidationError):
            start_payment(order=order, method=card_method, user=user)

    def test_starting_twice_reuses_the_open_attempt(self, catalogue, tenant_a, user, card_method):
        order = make_order(tenant_a, user)
        first = start_payment(order=order, method=card_method, user=user)
        second = start_payment(order=order, method=card_method, user=user)
        assert first.pk == second.pk


class TestCardPayment:
    def test_the_customer_sees_the_card_details(self, catalogue, tenant_a, user, card_method):
        from apps.payments.services import instructions_for

        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=card_method, user=user)
        instructions = instructions_for(payment)

        assert instructions.copyable == "1234"
        assert any(field["value"] == "Platform" for field in instructions.fields)

    def test_submitting_a_receipt_moves_the_order_to_review(
        self, catalogue, tenant_a, user, card_method
    ):
        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=card_method, user=user)

        submit_proof(payment=payment, user=user, upload=receipt_file())

        payment.refresh_from_db()
        order.refresh_from_db()
        assert payment.status == PaymentStatus.RECEIPT_SUBMITTED
        assert order.status == OrderStatus.RECEIPT_SUBMITTED.value

    def test_a_card_payment_requires_a_receipt(self, catalogue, tenant_a, user, card_method):
        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=card_method, user=user)

        with pytest.raises(ValidationError) as exc:
            submit_proof(payment=payment, user=user, upload=None)
        assert exc.value.code == "payment.receipt_required"


class TestCryptoPayment:
    def test_the_customer_sees_the_wallet_address(
        self, catalogue, tenant_a, user, crypto_method
    ):
        from apps.payments.services import instructions_for

        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=crypto_method, user=user)
        instructions = instructions_for(payment)

        assert instructions.copyable == "TXyz123"
        assert any("network" in note.lower() for note in instructions.notes)

    def test_a_transaction_hash_is_required(self, catalogue, tenant_a, user, crypto_method):
        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=crypto_method, user=user)

        with pytest.raises(ValidationError) as exc:
            submit_proof(payment=payment, user=user, tx_hash="")
        assert exc.value.code == "payment.tx_hash_required"

    def test_a_short_hash_is_rejected(self, catalogue, tenant_a, user, crypto_method):
        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=crypto_method, user=user)

        with pytest.raises(ValidationError):
            submit_proof(payment=payment, user=user, tx_hash="abc")

    def test_crypto_proof_needs_no_file(self, catalogue, tenant_a, user, crypto_method):
        order = make_order(tenant_a, user)
        payment = start_payment(order=order, method=crypto_method, user=user)

        submit_proof(payment=payment, user=user, tx_hash="0x" + "a" * 40)
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.RECEIPT_SUBMITTED

    def test_one_transaction_cannot_settle_two_orders(
        self, catalogue, tenant_a, user, crypto_method
    ):
        """SECURITY.md §8 — the reason `tx_hash` is globally unique."""
        tx = "0x" + "b" * 40

        first = start_payment(order=make_order(tenant_a, user), method=crypto_method, user=user)
        submit_proof(payment=first, user=user, tx_hash=tx)

        second = start_payment(order=make_order(tenant_a, user), method=crypto_method, user=user)
        with pytest.raises(ConflictError) as exc:
            submit_proof(payment=second, user=user, tx_hash=tx)
        assert exc.value.code == "payment.tx_hash_already_used"


class TestDuplicateReceipts:
    def test_the_same_image_on_another_order_is_flagged_not_blocked(
        self, catalogue, tenant_a, user, card_method
    ):
        """Blocking would strand a customer who legitimately paid twice by transfer."""
        first = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=first, user=user, upload=receipt_file(colour="red"))

        second = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=second, user=user, upload=receipt_file(colour="red"))

        second.refresh_from_db()
        assert second.status == PaymentStatus.RECEIPT_SUBMITTED
        assert "[auto]" in second.internal_note
        assert "already seen" in second.internal_note

    def test_a_different_image_is_not_flagged(self, catalogue, tenant_a, user, card_method):
        first = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=first, user=user, upload=receipt_file(colour="red"))

        second = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=second, user=user, upload=receipt_file(colour="blue"))

        second.refresh_from_db()
        assert "[auto]" not in (second.internal_note or "")


class TestReview:
    def _submitted(self, tenant, user, method) -> Payment:
        payment = start_payment(order=make_order(tenant, user), method=method, user=user)
        return submit_proof(payment=payment, user=user, upload=receipt_file())

    def test_finance_can_approve_and_the_order_becomes_paid(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        payment = self._submitted(tenant_a, user, card_method)
        approve_payment(payment=payment, staff=finance)

        payment.refresh_from_db()
        payment.order.refresh_from_db()
        assert payment.status == PaymentStatus.APPROVED
        assert payment.order.status == OrderStatus.PAID.value
        assert payment.order.paid_at is not None

    def test_support_cannot_approve_payments(
        self, catalogue, tenant_a, user, card_method, support
    ):
        """Least privilege: support handles tickets, not money."""
        payment = self._submitted(tenant_a, user, card_method)
        with pytest.raises(PermissionDeniedError):
            approve_payment(payment=payment, staff=support)

    def test_a_customer_cannot_approve_their_own_payment(
        self, catalogue, tenant_a, user, card_method
    ):
        payment = self._submitted(tenant_a, user, card_method)
        with pytest.raises(PermissionDeniedError):
            approve_payment(payment=payment, staff=user)

    def test_rejection_requires_a_reason(self, catalogue, tenant_a, user, card_method, finance):
        payment = self._submitted(tenant_a, user, card_method)
        with pytest.raises(ValidationError):
            reject_payment(payment=payment, staff=finance, reason="   ")

    def test_rejection_returns_the_order_to_the_customer(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        payment = self._submitted(tenant_a, user, card_method)
        reject_payment(payment=payment, staff=finance, reason="Amount does not match")

        payment.refresh_from_db()
        payment.order.refresh_from_db()
        assert payment.status == PaymentStatus.REJECTED
        assert payment.order.status == OrderStatus.PAYMENT_REJECTED.value
        assert payment.rejection_reason == "Amount does not match"

    def test_a_rejected_order_can_be_paid_again(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        payment = self._submitted(tenant_a, user, card_method)
        reject_payment(payment=payment, staff=finance, reason="Wrong amount")

        order = payment.order
        transition_order(
            order=order,
            target=OrderStatus.PENDING_PAYMENT,
            actor_type=Actor.CUSTOMER,
            user=user,
        )
        order.refresh_from_db()
        assert order.is_payable

    def test_approving_twice_is_idempotent(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        payment = self._submitted(tenant_a, user, card_method)
        approve_payment(payment=payment, staff=finance)
        again = approve_payment(payment=payment, staff=finance)
        assert again.status == PaymentStatus.APPROVED

    def test_an_already_rejected_payment_cannot_be_approved(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        payment = self._submitted(tenant_a, user, card_method)
        reject_payment(payment=payment, staff=finance, reason="No")

        with pytest.raises(ConflictError):
            approve_payment(payment=payment, staff=finance)

    def test_an_amount_mismatch_blocks_approval(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        """A stale payment row must not decide what was owed (SECURITY.md §8)."""
        payment = self._submitted(tenant_a, user, card_method)
        Payment.objects.filter(pk=payment.pk).update(amount_minor=1)
        payment.refresh_from_db()

        with pytest.raises(ConflictError) as exc:
            approve_payment(payment=payment, staff=finance)
        assert exc.value.code == "payment.amount_mismatch"

    def test_proof_cannot_be_replaced_during_review(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        payment = self._submitted(tenant_a, user, card_method)
        begin_review(payment=payment, staff=finance)

        with pytest.raises(ConflictError) as exc:
            submit_proof(payment=payment, user=user, upload=receipt_file(colour="green"))
        assert exc.value.code == "payment.under_review"


class TestNotifications:
    """The outbox relay is scheduled via ``transaction.on_commit``, which does not fire
    inside a test's rollback transaction — hence `django_capture_on_commit_callbacks`.
    That is the same code path production uses, just triggered explicitly.
    """

    def test_placing_an_order_notifies_the_owner(
        self, catalogue, tenant_a, user, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            make_order(tenant_a, user)

        assert Notification.objects.filter(
            recipient=user, event_type="order.pending_payment"
        ).exists()

    def test_approval_notifies_the_customer(
        self, catalogue, tenant_a, user, card_method, finance, django_capture_on_commit_callbacks
    ):
        payment = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=payment, user=user, upload=receipt_file())

        with django_capture_on_commit_callbacks(execute=True):
            approve_payment(payment=payment, staff=finance)

        assert Notification.objects.filter(recipient=user, event_type="order.paid").exists()

    def test_rejection_notifies_the_customer(
        self, catalogue, tenant_a, user, card_method, finance, django_capture_on_commit_callbacks
    ):
        payment = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=payment, user=user, upload=receipt_file())

        with django_capture_on_commit_callbacks(execute=True):
            reject_payment(payment=payment, staff=finance, reason="Unreadable receipt")

        assert Notification.objects.filter(
            recipient=user, event_type="order.payment_rejected"
        ).exists()

    def test_the_notification_carries_the_rejection_reason_to_the_customer(
        self, catalogue, tenant_a, user, card_method, finance, django_capture_on_commit_callbacks
    ):
        from apps.notifications.messages import render

        payment = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=payment, user=user, upload=receipt_file())

        with django_capture_on_commit_callbacks(execute=True):
            reject_payment(payment=payment, staff=finance, reason="Amount does not match")

        notification = Notification.objects.get(
            recipient=user, event_type="order.payment_rejected"
        )
        body = render(notification.body_key, notification.params, "en")
        assert str(payment.order.number) in body
        # Requiring a reason is pointless if the customer never sees it.
        assert "Amount does not match" in body

    def test_the_same_event_does_not_notify_twice(self, catalogue, tenant_a, user):
        """The outbox relay is at-least-once, so consumers must be idempotent."""
        from apps.notifications.services import notify_from_event

        order = make_order(tenant_a, user)
        payload = {
            "order_id": str(order.public_id),
            "number": order.number,
            "tenant_id": str(tenant_a.public_id),
        }
        notify_from_event("order.paid", payload)
        notify_from_event("order.paid", payload)

        assert (
            Notification.objects.filter(recipient=user, event_type="order.paid").count() == 1
        )

    def test_an_unknown_event_notifies_nobody(self, catalogue, tenant_a, user):
        from apps.notifications.services import notify_from_event

        assert notify_from_event("internal.debug", {"tenant_id": str(tenant_a.public_id)}) == 0


class TestDiscounts:
    def test_an_admin_discount_lowers_the_total(self, catalogue, tenant_a, user, finance):
        from apps.orders.services import apply_discount

        order = make_order(tenant_a, user)
        before = order.total_minor

        apply_discount(order=order, amount_minor=1000, reason="Goodwill", actor=finance)
        order.refresh_from_db()
        assert order.total_minor == before - 1000
        assert order.discount_reason == "Goodwill"

    def test_a_discount_needs_a_reason(self, catalogue, tenant_a, user, finance):
        from apps.orders.services import apply_discount

        order = make_order(tenant_a, user)
        with pytest.raises(ConflictError):
            apply_discount(order=order, amount_minor=1000, reason="", actor=finance)

    def test_a_paid_order_cannot_be_discounted(
        self, catalogue, tenant_a, user, card_method, finance
    ):
        from apps.orders.services import apply_discount

        payment = start_payment(order=make_order(tenant_a, user), method=card_method, user=user)
        submit_proof(payment=payment, user=user, upload=receipt_file())
        approve_payment(payment=payment, staff=finance)

        payment.order.refresh_from_db()
        with pytest.raises(ConflictError):
            apply_discount(order=payment.order, amount_minor=100, reason="Late", actor=finance)
