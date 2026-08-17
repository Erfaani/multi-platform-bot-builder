"""Payment use cases.

The order and the payment move together, always inside one transaction: an approved
payment on an unpaid order (or the reverse) is the failure mode that costs real money.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from apps.core.files import RECEIPT_POLICY, validate_and_sanitise
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.models import Order
from apps.orders.services import transition_order
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentReceipt,
    PaymentStatus,
    ReceiptScanStatus,
)
from apps.payments.providers import provider_for


def available_methods(*, currency: str, country: str = "", amount_minor: int = 0):
    """Methods a customer may actually use for this order.

    Filtering by currency is not cosmetic: an order carries exactly one currency
    (spec §13), so paying a USD order with a Rial card method must be impossible.
    """
    methods = PaymentMethod.objects.filter(is_enabled=True, currency=currency.upper())
    if country:
        methods = [
            m for m in methods if not m.country_scope or country.upper() in m.country_scope
        ]
    else:
        methods = list(methods)

    if amount_minor:
        methods = [m for m in methods if amount_minor >= m.minimum_amount_minor]
    return methods


@transaction.atomic
def start_payment(*, order: Order, method: PaymentMethod, user) -> Payment:
    """Open a payment attempt against an order."""
    if not order.is_payable:
        raise ConflictError(
            code="payment.order_not_payable",
            message="This order is not awaiting payment.",
        )

    if not method.is_enabled:
        raise ValidationError(
            code="payment.method_disabled", message="That payment method is unavailable."
        )

    if method.currency != order.currency:
        # Never convert. A mismatch here means the UI offered the wrong thing.
        raise ValidationError(
            code="payment.currency_mismatch",
            message="That payment method cannot be used for this order's currency.",
        )

    if order.total_minor < method.minimum_amount_minor:
        raise ValidationError(
            code="payment.below_minimum",
            message="This order is below the minimum for that payment method.",
        )

    # Reuse an open attempt rather than littering the order with abandoned ones.
    existing = order.payments.filter(
        payment_method=method, status=PaymentStatus.PENDING
    ).first()
    if existing is not None:
        return existing

    payment = Payment.objects.create(
        order=order,
        payment_method=method,
        amount_minor=order.total_minor,
        currency=order.currency,
        network=method.network,
        status=PaymentStatus.PENDING,
    )
    record_audit(
        actor=user,
        action="payment.started",
        resource_type="payment",
        resource_id=str(payment.public_id),
        tenant=order.tenant,
        metadata={"order": order.number, "method": method.provider_slug},
    )
    return payment


def instructions_for(payment: Payment):
    provider = provider_for(payment.payment_method)
    return provider.instructions(method=payment.payment_method, payment=payment)


def proof_requirements_for(method: PaymentMethod):
    return provider_for(method).proof_requirements(method=method)


@transaction.atomic
def submit_proof(
    *,
    payment: Payment,
    user,
    upload=None,
    tx_hash: str = "",
    sender_wallet: str = "",
    payer_note: str = "",
    ip: str | None = None,
) -> Payment:
    """Attach proof of payment and move the order into the review queue."""
    # Re-read under a row lock: the guards below must not depend on how fresh the
    # caller's in-memory object happens to be, or a stale copy walks straight past them.
    payment = Payment.objects.select_for_update().select_related(
        "order", "payment_method"
    ).get(pk=payment.pk)

    if payment.status in {PaymentStatus.APPROVED, PaymentStatus.REJECTED}:
        raise ConflictError(
            code="payment.already_reviewed",
            message="This payment has already been reviewed.",
        )
    if payment.status == PaymentStatus.UNDER_REVIEW:
        # Swapping the document mid-review would mean the reviewer approves something
        # other than what they looked at.
        raise ConflictError(
            code="payment.under_review",
            message="This payment is being reviewed and can no longer be changed.",
        )

    method = payment.payment_method
    provider = provider_for(method)
    requirements = provider.proof_requirements(method=method)

    data = provider.validate_proof(
        method=method,
        data={"tx_hash": tx_hash, "sender_wallet": sender_wallet},
    )

    if requirements.requires_file and upload is None:
        raise ValidationError(
            code="payment.receipt_required",
            field_errors={"file": ["A payment receipt is required."]},
        )

    if requirements.requires_tx_hash:
        candidate = data.get("tx_hash", "")
        clash = (
            Payment.objects.filter(tx_hash=candidate)
            .exclude(pk=payment.pk)
            .exists()
        )
        if clash:
            # One on-chain payment cannot settle two orders (SECURITY.md §8).
            raise ConflictError(
                code="payment.tx_hash_already_used",
                message="That transaction has already been submitted for another order.",
            )
        payment.tx_hash = candidate
        payment.sender_wallet = data.get("sender_wallet", "")[:128]

    duplicate_of = None
    if upload is not None:
        safe = validate_and_sanitise(upload, RECEIPT_POLICY)

        duplicate = (
            PaymentReceipt.objects.filter(sha256=safe.sha256)
            .exclude(payment__order_id=payment.order_id)
            .select_related("payment__order")
            .first()
        )
        if duplicate is not None:
            # Flagged, not blocked: a legitimate customer can pay twice with one
            # transfer image, and a hard block would strand them. Finance decides.
            duplicate_of = duplicate.payment.order.number

        receipt = PaymentReceipt(
            payment=payment,
            original_filename=safe.original_filename,
            content_type=safe.content_type,
            size_bytes=safe.size_bytes,
            sha256=safe.sha256,
            scan_status=ReceiptScanStatus.PENDING,
            uploaded_by=user if getattr(user, "pk", None) else None,
            uploaded_ip=ip,
        )
        receipt.file.save(safe.filename, safe.content, save=False)
        receipt.save()

        from apps.payments.tasks import scan_receipt

        transaction.on_commit(lambda: scan_receipt.delay(receipt.pk))

    payment.payer_note = payer_note[:255]
    payment.status = PaymentStatus.RECEIPT_SUBMITTED
    payment.submitted_at = timezone.now()
    if duplicate_of:
        payment.internal_note = (
            f"{payment.internal_note}\n[auto] Receipt image already seen on order "
            f"#{duplicate_of}."
        ).strip()
    payment.save()

    transition_order(
        order=payment.order,
        target=OrderStatus.RECEIPT_SUBMITTED,
        actor_type=Actor.CUSTOMER,
        user=user,
        reason="Proof of payment submitted",
        metadata={"payment": str(payment.public_id), "duplicate_of_order": duplicate_of},
    )

    record_audit(
        actor=user,
        action="payment.proof_submitted",
        resource_type="payment",
        resource_id=str(payment.public_id),
        tenant=payment.order.tenant,
        ip=ip,
        metadata={"duplicate_of_order": duplicate_of},
    )
    return payment


@transaction.atomic
def begin_review(*, payment: Payment, staff) -> Payment:
    """Claim a payment for review, so two agents do not both act on it."""
    _require_scope(staff, "payments.review")

    locked = Payment.objects.select_for_update().get(pk=payment.pk)
    if locked.status != PaymentStatus.RECEIPT_SUBMITTED:
        raise ConflictError(
            code="payment.not_reviewable", message="This payment is not awaiting review."
        )

    locked.status = PaymentStatus.UNDER_REVIEW
    locked.save(update_fields=["status", "updated_at"])

    transition_order(
        order=locked.order,
        target=OrderStatus.PAYMENT_REVIEW,
        actor_type=Actor.STAFF,
        user=staff,
        reason="Review started",
    )
    return locked


@transaction.atomic
def approve_payment(*, payment: Payment, staff, note: str = "") -> Payment:
    """Approve a payment and mark the order paid."""
    _require_scope(staff, "payments.review")

    locked = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)

    if locked.status == PaymentStatus.APPROVED:
        return locked  # idempotent
    if locked.status not in {PaymentStatus.RECEIPT_SUBMITTED, PaymentStatus.UNDER_REVIEW}:
        raise ConflictError(
            code="payment.not_reviewable", message="This payment cannot be approved."
        )

    # Re-validate the amount against the order at approval time. A stale payment row
    # must never be the thing that decides what was owed (SECURITY.md §8).
    if locked.amount_minor != locked.order.total_minor or locked.currency != locked.order.currency:
        raise ConflictError(
            code="payment.amount_mismatch",
            message=(
                "The payment amount no longer matches the order total. "
                "Re-check the order before approving."
            ),
        )

    if locked.order.status not in {
        OrderStatus.RECEIPT_SUBMITTED.value,
        OrderStatus.PAYMENT_REVIEW.value,
    }:
        raise ConflictError(
            code="order.not_awaiting_payment",
            message="This order is not awaiting payment approval.",
        )

    if locked.order.status == OrderStatus.RECEIPT_SUBMITTED.value:
        transition_order(
            order=locked.order,
            target=OrderStatus.PAYMENT_REVIEW,
            actor_type=Actor.STAFF,
            user=staff,
            reason="Review started",
        )

    locked.status = PaymentStatus.APPROVED
    locked.reviewed_at = timezone.now()
    locked.reviewed_by = staff
    if note:
        locked.internal_note = f"{locked.internal_note}\n{note}".strip()
    locked.save()

    transition_order(
        order=locked.order,
        target=OrderStatus.PAID,
        actor_type=Actor.STAFF,
        user=staff,
        reason="Payment approved",
        metadata={"payment": str(locked.public_id)},
    )

    record_audit(
        actor=staff,
        action="payment.approved",
        resource_type="payment",
        resource_id=str(locked.public_id),
        tenant=locked.order.tenant,
        metadata={"order": locked.order.number, "amount_minor": locked.amount_minor},
    )
    return locked


@transaction.atomic
def reject_payment(*, payment: Payment, staff, reason: str, note: str = "") -> Payment:
    """Reject a payment. A reason is mandatory — the customer has to be told why."""
    _require_scope(staff, "payments.review")

    if not reason.strip():
        raise ValidationError(
            code="payment.rejection_reason_required",
            field_errors={"reason": ["A rejection reason is required."]},
        )

    locked = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
    if locked.status in {PaymentStatus.APPROVED, PaymentStatus.REJECTED}:
        raise ConflictError(
            code="payment.already_reviewed", message="This payment has already been reviewed."
        )

    locked.status = PaymentStatus.REJECTED
    locked.reviewed_at = timezone.now()
    locked.reviewed_by = staff
    locked.rejection_reason = reason[:255]
    if note:
        locked.internal_note = f"{locked.internal_note}\n{note}".strip()
    locked.save()

    transition_order(
        order=locked.order,
        target=OrderStatus.PAYMENT_REJECTED,
        actor_type=Actor.STAFF,
        user=staff,
        reason=reason[:255],
        metadata={"payment": str(locked.public_id)},
    )

    record_audit(
        actor=staff,
        action="payment.rejected",
        resource_type="payment",
        resource_id=str(locked.public_id),
        tenant=locked.order.tenant,
        metadata={"order": locked.order.number, "reason": reason},
    )
    return locked


def _require_scope(staff, scope: str) -> None:
    from apps.accounts.services import has_scope

    if staff is None or not getattr(staff, "is_authenticated", False):
        raise PermissionDeniedError()
    if not has_scope(staff, scope):
        raise PermissionDeniedError(
            code="payments.review_forbidden",
            message="Reviewing payments requires the finance role.",
        )


def get_payment_for_tenant(*, public_id: str, tenant) -> Payment:
    payment = (
        Payment.objects.filter(public_id=public_id, order__tenant=tenant)
        .select_related("order", "payment_method")
        .first()
    )
    if payment is None:
        raise NotFoundError()
    return payment
