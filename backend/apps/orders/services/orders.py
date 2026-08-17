"""Order use cases.

`transition_order` is the **only** way an order's status changes. Nothing else assigns
to `order.status` — that is what makes the allow-list in `domain/state_machine.py`
actually binding rather than advisory.
"""

from __future__ import annotations

from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from apps.core.events import publish
from apps.orders.domain.state_machine import (
    Actor,
    IllegalTransition,
    OrderStatus,
    TransitionNotPermitted,
    check,
)
from apps.orders.models import Order, OrderEvent, OrderItem, OrderKind, Quote

#: Human-facing order numbers start here so the platform's first sale is not #1.
ORDER_NUMBER_START = 10_000


def next_order_number() -> int:
    """Next order number from a database sequence.

    A sequence rather than `MAX(number) + 1` or `COUNT(*)`: those race under concurrent
    checkout and would hand two customers the same order number.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('order_number_seq')")
        return int(cursor.fetchone()[0])


@transaction.atomic
def place_order(*, quote: Quote, tenant, user, idempotency_key: str = "") -> Order:
    """Turn a priced quote into an order.

    The quote's frozen lines are copied verbatim. Nothing is re-priced here — the
    customer buys what they were shown (spec §12).
    """
    if quote.tenant_id != tenant.pk:
        raise NotFoundError()

    # Re-read under a row lock rather than trusting the caller's in-memory copy.
    # Two concurrent checkouts (or a stale object after an earlier call) would
    # otherwise both see `converted_order_id = None` and create two orders.
    quote = Quote.objects.select_for_update().get(pk=quote.pk)

    if quote.converted_order_id:
        existing = Order.objects.filter(pk=quote.converted_order_id).first()
        if existing is not None:
            # Re-submitting checkout must not create a second order.
            return existing

    if quote.is_expired:
        raise ConflictError(
            code="quote.expired",
            message="This quote has expired. Please rebuild it to get current prices.",
        )

    items = list(quote.items.select_related("price_version").all())
    if not items:
        raise ConflictError(
            code="quote.empty", message="This quote has no priced items."
        )

    order = Order.objects.create(
        tenant=tenant,
        number=next_order_number(),
        quote=quote,
        placed_by=user if getattr(user, "pk", None) else None,
        status=OrderStatus.DRAFT.value,
        template=quote.template,
        kind=OrderKind.ADDON if quote.target_bot_id else OrderKind.NEW,
        target_bot=quote.target_bot,
        platforms=list(quote.platforms),
        features=list(quote.resolved_features),
        business_snapshot=dict(quote.business_draft or {}),
        locale=quote.locale,
        created_via=quote.created_via,
        currency=quote.currency,
        subtotal_once_minor=quote.subtotal_once_minor,
        subtotal_recurring_minor=quote.subtotal_recurring_minor,
        discount_minor=quote.discount_minor,
        tax_minor=quote.tax_minor,
        total_minor=quote.total_minor,
    )

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                price_key=item.price_key,
                label_key=item.label_key,
                feature_slug=item.feature_slug,
                price_version=item.price_version,
                unit_amount_minor=item.unit_amount_minor,
                quantity=item.quantity,
                amount_minor=item.amount_minor,
                currency=item.currency,
                billing_kind=item.billing_kind,
                sort_order=item.sort_order,
                snapshot={
                    "price_version_id": item.price_version_id,
                    "price_list": quote.price_list.slug,
                    "quoted_at": quote.created_at.isoformat(),
                },
            )
            for item in items
        ]
    )

    Quote.objects.filter(pk=quote.pk).update(converted_order_id=order.pk)

    transition_order(
        order=order,
        target=OrderStatus.PENDING_PAYMENT,
        actor_type=Actor.CUSTOMER,
        user=user,
        reason="Order placed",
    )

    record_audit(
        actor=user,
        action="order.placed",
        resource_type="order",
        resource_id=str(order.public_id),
        tenant=tenant,
        metadata={"number": order.number, "total_minor": order.total_minor},
    )
    return order


@transaction.atomic
def transition_order(
    *,
    order: Order,
    target: OrderStatus | str,
    actor_type: Actor | str,
    user=None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
    scopes: set[str] | None = None,
) -> Order:
    """Move an order, enforcing the allow-list. The only legal way to change status."""
    target = OrderStatus(target)
    actor_type = Actor(actor_type)

    # Re-read under a row lock: two concurrent approvals must not both succeed.
    locked = Order.objects.select_for_update().get(pk=order.pk)
    source = OrderStatus(locked.status)

    if source == target and target != OrderStatus.RECEIPT_SUBMITTED:
        return locked  # idempotent no-op

    if actor_type is Actor.STAFF and scopes is None:
        from apps.accounts.services import user_scopes

        scopes = user_scopes(user) if user is not None else set()

    try:
        check(source=source, target=target, actor=actor_type, scopes=scopes)
    except IllegalTransition as exc:
        raise ConflictError(code="order.illegal_transition", message=str(exc)) from exc
    except TransitionNotPermitted as exc:
        raise PermissionDeniedError(code="order.transition_forbidden", message=str(exc)) from exc

    locked.status = target.value
    stamps = ["status", "updated_at"]

    now = timezone.now()
    if target is OrderStatus.PENDING_PAYMENT and locked.placed_at is None:
        locked.placed_at = now
        stamps.append("placed_at")
    elif target is OrderStatus.PAID and locked.paid_at is None:
        locked.paid_at = now
        stamps.append("paid_at")
    elif target is OrderStatus.ACTIVE and locked.activated_at is None:
        locked.activated_at = now
        stamps.append("activated_at")
    elif target is OrderStatus.CANCELLED:
        locked.cancelled_at = now
        stamps.append("cancelled_at")

    locked.save(update_fields=stamps)

    OrderEvent.objects.create(
        order=locked,
        from_status=source.value,
        to_status=target.value,
        actor_type=actor_type.value,
        actor=user if getattr(user, "pk", None) else None,
        reason=reason[:255],
        metadata=metadata or {},
    )

    # Written in this transaction, so the event cannot exist without the move
    # (ARCHITECTURE.md §9).
    publish(
        f"order.{target.value.lower()}",
        {
            "order_id": str(locked.public_id),
            "number": locked.number,
            "tenant_id": str(locked.tenant.public_id),
            "from_status": source.value,
            "to_status": target.value,
            "total_minor": locked.total_minor,
            "currency": locked.currency,
            "locale": locked.locale,
            # Carried through so a rejection notification can tell the customer *why*.
            # Requiring a reason and then not showing it would be pointless.
            "reason": reason,
        },
    )

    order.status = locked.status
    return locked


def cancel_order(*, order: Order, user, actor_type: Actor = Actor.CUSTOMER, reason: str = "") -> Order:
    return transition_order(
        order=order,
        target=OrderStatus.CANCELLED,
        actor_type=actor_type,
        user=user,
        reason=reason or "Cancelled by customer",
    )


@transaction.atomic
def apply_discount(*, order: Order, amount_minor: int, reason: str, actor) -> Order:
    """Admin-applied manual adjustment (DATABASE.md §4).

    Only before payment: discounting an order that has already been paid would make
    the order disagree with the money actually received.
    """
    if order.is_paid_or_beyond:
        raise ConflictError(
            code="order.already_paid",
            message="A paid order cannot be discounted; issue a refund instead.",
        )
    if amount_minor < 0 or amount_minor > order.subtotal_once_minor + order.subtotal_recurring_minor:
        raise ConflictError(
            code="order.invalid_discount", message="The discount must be between zero and the subtotal."
        )
    if not reason.strip():
        raise ConflictError(
            code="order.discount_reason_required", message="A discount needs a recorded reason."
        )

    before = order.total_minor
    order.discount_minor = amount_minor
    order.discount_reason = reason[:255]
    order.total_minor = (
        order.subtotal_once_minor + order.subtotal_recurring_minor - amount_minor + order.tax_minor
    )
    order.save(update_fields=["discount_minor", "discount_reason", "total_minor", "updated_at"])

    record_audit(
        actor=actor,
        action="order.discount_applied",
        resource_type="order",
        resource_id=str(order.public_id),
        tenant=order.tenant,
        metadata={"from_minor": before, "to_minor": order.total_minor, "reason": reason},
    )
    return order


def get_order_for_tenant(*, public_id: str, tenant) -> Order:
    order = (
        Order.objects.filter(public_id=public_id, tenant=tenant)
        .select_related("template", "tenant")
        .first()
    )
    if order is None:
        raise NotFoundError()
    return order
