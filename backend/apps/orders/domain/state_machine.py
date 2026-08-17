"""Order state machine (spec §19).

Pure domain logic — no ORM, no Django — so every edge can be tested exhaustively.

Two rules make this safe:

1. **Allow-list, not deny-list.** A transition that is not declared is impossible. Adding
   a state cannot accidentally open a path to `PAID`.
2. **Every edge names who may take it.** "Customers cannot mark their own order paid" is
   encoded here rather than being spread across view permissions, where one missing check
   would be a free bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    RECEIPT_SUBMITTED = "RECEIPT_SUBMITTED"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    PAYMENT_REJECTED = "PAYMENT_REJECTED"
    PAID = "PAID"
    PROVISIONING = "PROVISIONING"
    CONFIGURING = "CONFIGURING"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    GRACE_PERIOD = "GRACE_PERIOD"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class Actor(StrEnum):
    CUSTOMER = "CUSTOMER"
    STAFF = "STAFF"
    SYSTEM = "SYSTEM"


#: States from which a customer may still walk away.
CANCELLABLE = frozenset(
    {
        OrderStatus.DRAFT,
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PAYMENT_REJECTED,
    }
)

#: Money has changed hands or a bot exists; nothing here may be silently discarded.
TERMINAL = frozenset({OrderStatus.CANCELLED})

#: Provisioning is in flight (Phase 4 drives these).
PROVISIONING_STATES = frozenset(
    {OrderStatus.PROVISIONING, OrderStatus.CONFIGURING, OrderStatus.DEPLOYING}
)


@dataclass(frozen=True, slots=True)
class Transition:
    source: OrderStatus
    target: OrderStatus
    allowed_actors: frozenset[Actor]
    #: Staff scope required when a STAFF actor takes this edge.
    required_scope: str | None = None
    description: str = ""


def _t(source, target, *actors, scope=None, description=""):
    return Transition(source, target, frozenset(actors), scope, description)


#: The complete set of legal moves. Anything absent is illegal by construction.
TRANSITIONS: tuple[Transition, ...] = (
    # --- customer places the order -------------------------------------------------
    _t(
        OrderStatus.DRAFT,
        OrderStatus.PENDING_PAYMENT,
        Actor.CUSTOMER,
        Actor.SYSTEM,
        description="Order placed from a quote; awaiting payment.",
    ),
    # --- manual payment round-trip --------------------------------------------------
    _t(
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.RECEIPT_SUBMITTED,
        Actor.CUSTOMER,
        description="Customer uploaded proof of payment.",
    ),
    _t(
        OrderStatus.RECEIPT_SUBMITTED,
        OrderStatus.PAYMENT_REVIEW,
        Actor.STAFF,
        Actor.SYSTEM,
        scope="payments.review",
        description="Finance picked the receipt up for review.",
    ),
    # A customer may replace a receipt while it is still queued, but not once a
    # reviewer has opened it — otherwise the document under review could change.
    _t(
        OrderStatus.RECEIPT_SUBMITTED,
        OrderStatus.RECEIPT_SUBMITTED,
        Actor.CUSTOMER,
        description="Customer replaced the receipt before review started.",
    ),
    _t(
        OrderStatus.PAYMENT_REVIEW,
        OrderStatus.PAID,
        Actor.STAFF,
        scope="payments.review",
        description="Payment approved.",
    ),
    _t(
        OrderStatus.PAYMENT_REVIEW,
        OrderStatus.PAYMENT_REJECTED,
        Actor.STAFF,
        scope="payments.review",
        description="Payment rejected with a reason.",
    ),
    _t(
        OrderStatus.RECEIPT_SUBMITTED,
        OrderStatus.PAYMENT_REJECTED,
        Actor.STAFF,
        scope="payments.review",
        description="Rejected without a separate review step.",
    ),
    _t(
        OrderStatus.PAYMENT_REJECTED,
        OrderStatus.PENDING_PAYMENT,
        Actor.CUSTOMER,
        Actor.STAFF,
        description="Customer may try again after a rejection.",
    ),
    # --- provisioning (Phase 4 drives these) ----------------------------------------
    _t(OrderStatus.PAID, OrderStatus.PROVISIONING, Actor.SYSTEM, description="Saga started."),
    _t(OrderStatus.PROVISIONING, OrderStatus.CONFIGURING, Actor.SYSTEM),
    _t(OrderStatus.CONFIGURING, OrderStatus.DEPLOYING, Actor.SYSTEM),
    _t(OrderStatus.DEPLOYING, OrderStatus.ACTIVE, Actor.SYSTEM, description="Bot is live."),
    _t(OrderStatus.PROVISIONING, OrderStatus.FAILED, Actor.SYSTEM),
    _t(OrderStatus.CONFIGURING, OrderStatus.FAILED, Actor.SYSTEM),
    _t(OrderStatus.DEPLOYING, OrderStatus.FAILED, Actor.SYSTEM),
    _t(
        OrderStatus.FAILED,
        OrderStatus.PROVISIONING,
        Actor.STAFF,
        Actor.SYSTEM,
        scope="provisioning.manage",
        description="Retry after a failure; the saga resumes.",
    ),
    # --- lifecycle (Phase 9: apps.subscriptions drives the SYSTEM edges on schedule) --
    _t(
        OrderStatus.ACTIVE,
        OrderStatus.GRACE_PERIOD,
        Actor.SYSTEM,
        description="The billing period ended unpaid; the bot keeps working during the grace window.",
    ),
    _t(
        OrderStatus.GRACE_PERIOD,
        OrderStatus.ACTIVE,
        Actor.STAFF,
        Actor.SYSTEM,
        scope="subscriptions.manage",
        description="Renewed before the grace period ran out.",
    ),
    _t(
        OrderStatus.GRACE_PERIOD,
        OrderStatus.SUSPENDED,
        Actor.STAFF,
        Actor.SYSTEM,
        scope="subscriptions.manage",
        description="Grace period ran out unpaid.",
    ),
    _t(
        OrderStatus.ACTIVE,
        OrderStatus.SUSPENDED,
        Actor.STAFF,
        Actor.SYSTEM,
        scope="subscriptions.manage",
        description="An admin suspended the bot directly, skipping the grace period.",
    ),
    _t(
        OrderStatus.SUSPENDED,
        OrderStatus.ACTIVE,
        Actor.STAFF,
        Actor.SYSTEM,
        scope="subscriptions.manage",
        description="Reinstated after payment or review.",
    ),
    # --- cancellation ----------------------------------------------------------------
    *(
        _t(source, OrderStatus.CANCELLED, Actor.CUSTOMER, Actor.STAFF)
        for source in CANCELLABLE
    ),
)

_INDEX: dict[tuple[OrderStatus, OrderStatus], Transition] = {
    (t.source, t.target): t for t in TRANSITIONS
}


class IllegalTransition(Exception):
    """The requested move is not on the allow-list."""

    def __init__(self, source, target, reason: str = "") -> None:
        self.source = source
        self.target = target
        self.reason = reason
        super().__init__(reason or f"Cannot move an order from {source} to {target}.")


class TransitionNotPermitted(Exception):
    """The move is legal, but not for this actor."""


def find(source: OrderStatus, target: OrderStatus) -> Transition | None:
    return _INDEX.get((OrderStatus(source), OrderStatus(target)))


def allowed_targets(source: OrderStatus, actor: Actor | None = None) -> list[OrderStatus]:
    """Every state reachable from ``source``, optionally filtered by who is asking."""
    source = OrderStatus(source)
    return [
        t.target
        for t in TRANSITIONS
        if t.source == source and (actor is None or actor in t.allowed_actors)
    ]


def check(
    *,
    source: OrderStatus,
    target: OrderStatus,
    actor: Actor,
    scopes: set[str] | None = None,
) -> Transition:
    """Validate a move, or raise. Callers must go through here — never assign status."""
    source, target, actor = OrderStatus(source), OrderStatus(target), Actor(actor)

    transition = find(source, target)
    if transition is None:
        raise IllegalTransition(
            source,
            target,
            f"{source} → {target} is not a valid order transition. "
            f"Allowed from {source}: {', '.join(allowed_targets(source)) or 'none'}.",
        )

    if actor not in transition.allowed_actors:
        raise TransitionNotPermitted(
            f"A {actor} may not move an order from {source} to {target}."
        )

    if actor is Actor.STAFF and transition.required_scope:
        held = scopes or set()
        if "*" not in held and transition.required_scope not in held:
            raise TransitionNotPermitted(
                f"This action requires the {transition.required_scope!r} scope."
            )

    return transition


def is_paid_or_beyond(status: OrderStatus) -> bool:
    """True once money has been accepted — used to lock the configuration."""
    return OrderStatus(status) in {
        OrderStatus.PAID,
        *PROVISIONING_STATES,
        OrderStatus.ACTIVE,
        OrderStatus.GRACE_PERIOD,
        OrderStatus.SUSPENDED,
        OrderStatus.FAILED,
    }
