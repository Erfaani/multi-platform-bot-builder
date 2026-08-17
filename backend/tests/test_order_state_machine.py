"""The order state machine. Pure unit tests — no database.

The point of these is not that the happy path works; it is that the *illegal* paths are
closed. A missing edge check here is a free bot.
"""

from __future__ import annotations

import pytest

from apps.orders.domain.state_machine import (
    TRANSITIONS,
    Actor,
    IllegalTransition,
    OrderStatus,
    TransitionNotPermitted,
    allowed_targets,
    check,
    find,
    is_paid_or_beyond,
)

S = OrderStatus


class TestAllowList:
    def test_placing_an_order_is_allowed(self):
        assert check(source=S.DRAFT, target=S.PENDING_PAYMENT, actor=Actor.CUSTOMER)

    def test_an_undeclared_transition_is_impossible(self):
        with pytest.raises(IllegalTransition):
            check(source=S.DRAFT, target=S.ACTIVE, actor=Actor.SYSTEM)

    def test_cannot_skip_payment(self):
        """The whole point of the allow-list."""
        with pytest.raises(IllegalTransition):
            check(source=S.PENDING_PAYMENT, target=S.PAID, actor=Actor.SYSTEM)

    def test_cannot_reverse_a_paid_order_to_pending(self):
        with pytest.raises(IllegalTransition):
            check(source=S.PAID, target=S.PENDING_PAYMENT, actor=Actor.STAFF, scopes={"*"})

    def test_cancelled_is_terminal(self):
        assert allowed_targets(S.CANCELLED) == []

    def test_active_cannot_be_cancelled(self):
        """A running bot is suspended, never silently cancelled."""
        with pytest.raises(IllegalTransition):
            check(source=S.ACTIVE, target=S.CANCELLED, actor=Actor.STAFF, scopes={"*"})


class TestActorPermissions:
    def test_a_customer_cannot_mark_their_own_order_paid(self):
        """The single most valuable check in this file."""
        with pytest.raises(TransitionNotPermitted):
            check(source=S.PAYMENT_REVIEW, target=S.PAID, actor=Actor.CUSTOMER)

    def test_a_customer_cannot_approve_by_pretending_to_be_the_system(self):
        with pytest.raises(TransitionNotPermitted):
            check(source=S.PAYMENT_REVIEW, target=S.PAID, actor=Actor.SYSTEM)

    def test_staff_need_the_finance_scope_to_approve(self):
        with pytest.raises(TransitionNotPermitted):
            check(source=S.PAYMENT_REVIEW, target=S.PAID, actor=Actor.STAFF, scopes={"support.manage"})

    def test_finance_scope_permits_approval(self):
        assert check(
            source=S.PAYMENT_REVIEW, target=S.PAID, actor=Actor.STAFF, scopes={"payments.review"}
        )

    def test_superuser_wildcard_permits_approval(self):
        assert check(source=S.PAYMENT_REVIEW, target=S.PAID, actor=Actor.STAFF, scopes={"*"})

    def test_a_customer_cannot_suspend_their_own_order(self):
        with pytest.raises(TransitionNotPermitted):
            check(source=S.ACTIVE, target=S.SUSPENDED, actor=Actor.CUSTOMER)

    def test_a_customer_may_cancel_before_paying(self):
        assert check(source=S.PENDING_PAYMENT, target=S.CANCELLED, actor=Actor.CUSTOMER)

    def test_a_customer_may_retry_after_rejection(self):
        assert check(source=S.PAYMENT_REJECTED, target=S.PENDING_PAYMENT, actor=Actor.CUSTOMER)


class TestPaymentRoundTrip:
    def test_full_happy_path_is_connected(self):
        path = [
            S.DRAFT,
            S.PENDING_PAYMENT,
            S.RECEIPT_SUBMITTED,
            S.PAYMENT_REVIEW,
            S.PAID,
            S.PROVISIONING,
            S.CONFIGURING,
            S.DEPLOYING,
            S.ACTIVE,
        ]
        for source, target in zip(path, path[1:], strict=False):
            assert find(source, target) is not None, f"{source} → {target} is missing"

    def test_rejection_returns_the_customer_to_payment(self):
        assert find(S.PAYMENT_REVIEW, S.PAYMENT_REJECTED)
        assert find(S.PAYMENT_REJECTED, S.PENDING_PAYMENT)

    def test_a_receipt_can_be_replaced_before_review(self):
        assert check(
            source=S.RECEIPT_SUBMITTED, target=S.RECEIPT_SUBMITTED, actor=Actor.CUSTOMER
        )

    def test_a_receipt_cannot_be_replaced_during_review(self):
        """Otherwise the document approved differs from the one examined."""
        with pytest.raises(IllegalTransition):
            check(source=S.PAYMENT_REVIEW, target=S.RECEIPT_SUBMITTED, actor=Actor.CUSTOMER)


class TestProvisioning:
    def test_only_the_system_drives_provisioning(self):
        for source, target in (
            (S.PAID, S.PROVISIONING),
            (S.PROVISIONING, S.CONFIGURING),
            (S.CONFIGURING, S.DEPLOYING),
            (S.DEPLOYING, S.ACTIVE),
        ):
            assert check(source=source, target=target, actor=Actor.SYSTEM)
            with pytest.raises(TransitionNotPermitted):
                check(source=source, target=target, actor=Actor.CUSTOMER)

    def test_every_provisioning_step_can_fail(self):
        for source in (S.PROVISIONING, S.CONFIGURING, S.DEPLOYING):
            assert find(source, S.FAILED) is not None

    def test_a_failure_can_be_retried_by_ops(self):
        assert check(
            source=S.FAILED,
            target=S.PROVISIONING,
            actor=Actor.STAFF,
            scopes={"provisioning.manage"},
        )

    def test_a_customer_cannot_retry_provisioning(self):
        with pytest.raises(TransitionNotPermitted):
            check(source=S.FAILED, target=S.PROVISIONING, actor=Actor.CUSTOMER)


class TestIntrospection:
    def test_allowed_targets_can_be_filtered_by_actor(self):
        customer = allowed_targets(S.PENDING_PAYMENT, Actor.CUSTOMER)
        assert S.RECEIPT_SUBMITTED in customer
        assert S.CANCELLED in customer
        assert S.PAID not in customer

    def test_paid_or_beyond_locks_the_configuration(self):
        assert is_paid_or_beyond(S.PAID)
        assert is_paid_or_beyond(S.ACTIVE)
        assert is_paid_or_beyond(S.SUSPENDED)
        assert not is_paid_or_beyond(S.PENDING_PAYMENT)
        assert not is_paid_or_beyond(S.PAYMENT_REJECTED)

    def test_no_transition_leads_out_of_a_terminal_state(self):
        assert not [t for t in TRANSITIONS if t.source == S.CANCELLED]

    def test_every_transition_names_at_least_one_actor(self):
        assert all(t.allowed_actors for t in TRANSITIONS)

    def test_no_duplicate_edges(self):
        edges = [(t.source, t.target) for t in TRANSITIONS]
        assert len(edges) == len(set(edges))

    def test_paid_is_only_reachable_through_review(self):
        """If another path to PAID is ever added, this test should fail loudly."""
        sources = {t.source for t in TRANSITIONS if t.target == S.PAID}
        assert sources == {S.PAYMENT_REVIEW}
