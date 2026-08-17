"""Subscriptions (Phase 9): the billing cycle, the expiry sweep, and suspension that
actually disables the runtime and removes the webhook."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.subscriptions import services
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.subscriptions.tasks import sweep_subscriptions

pytestmark = pytest.mark.django_db


@pytest.fixture
def finance_staff(db):
    """A platform staff member with `subscriptions.manage` — distinct from a tenant
    `user`, who has no platform-staff scopes at all (`Actor.STAFF` transitions are
    checked against `apps.accounts` staff scopes, never tenant roles)."""
    from apps.accounts.models import StaffRole, User, UserStaffRole

    staff = User.objects.create_user(email="finance@example.com", password="TestPassw0rd!23")
    UserStaffRole.objects.create(user=staff, role=StaffRole.FINANCE_AGENT)
    return staff


class TestStartAndAddRecurringAmount:
    def test_provisioning_creates_a_subscription(self, provisioned_bot):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert subscription.currency == provisioned_bot.currency
        assert subscription.current_period_end > timezone.now()

    def test_start_is_idempotent(self, provisioned_bot):
        first = Subscription.objects.get(bot=provisioned_bot)
        again = services.start(bot=provisioned_bot, order=provisioned_bot.origin_order)
        assert again.pk == first.pk

    def test_an_addon_order_adds_to_the_recurring_amount(self, provisioned_bot):
        from apps.orders.models import Order

        subscription = Subscription.objects.get(bot=provisioned_bot)
        before = subscription.monthly_amount_minor

        addon_order = Order.objects.filter(pk=provisioned_bot.origin_order_id).first()
        addon_order.subtotal_recurring_minor = 5000
        updated = services.add_recurring_amount(bot=provisioned_bot, order=addon_order)

        assert updated.monthly_amount_minor == before + 5000

    def test_a_zero_recurring_addon_is_a_no_op(self, provisioned_bot):
        from apps.orders.models import Order

        subscription = Subscription.objects.get(bot=provisioned_bot)
        before = subscription.monthly_amount_minor
        order = Order.objects.filter(pk=provisioned_bot.origin_order_id).first()
        order.subtotal_recurring_minor = 0

        updated = services.add_recurring_amount(bot=provisioned_bot, order=order)
        assert updated.monthly_amount_minor == before


class TestGracePeriodAndSuspension:
    def test_entering_grace_period_sets_the_deadline_and_mirrors_the_order(self, provisioned_bot):
        subscription = Subscription.objects.get(bot=provisioned_bot)

        updated = services.enter_grace_period(subscription=subscription)

        assert updated.status == SubscriptionStatus.GRACE_PERIOD
        assert updated.grace_period_ends_at is not None
        provisioned_bot.origin_order.refresh_from_db()
        assert provisioned_bot.origin_order.status == OrderStatus.GRACE_PERIOD.value

    def test_entering_grace_period_twice_is_idempotent(self, provisioned_bot):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        first = services.enter_grace_period(subscription=subscription)
        again = services.enter_grace_period(subscription=first)
        assert again.grace_period_ends_at == first.grace_period_ends_at

    def test_suspend_disables_every_instance_and_removes_its_webhook(self, provisioned_bot, fake_transport):
        from apps.bots.models import BotPlatformInstance

        subscription = Subscription.objects.get(bot=provisioned_bot)
        instance = provisioned_bot.instances.get(platform="telegram")
        assert instance.status == BotPlatformInstance.Status.ACTIVE

        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM, reason="test")

        provisioned_bot.refresh_from_db()
        instance.refresh_from_db()
        subscription.refresh_from_db()
        assert provisioned_bot.status == "SUSPENDED"
        assert instance.status == BotPlatformInstance.Status.SUSPENDED
        assert subscription.status == SubscriptionStatus.SUSPENDED
        assert subscription.suspended_at is not None
        assert fake_transport.called("deleteWebhook")

    def test_a_suspended_bot_stops_answering_the_webhook(self, provisioned_bot, fake_transport):
        from apps.bot_runtime.context import load_instance

        subscription = Subscription.objects.get(bot=provisioned_bot)
        instance = provisioned_bot.instances.get(platform="telegram")
        assert load_instance("telegram", str(instance.public_id)) is not None

        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)

        assert load_instance("telegram", str(instance.public_id)) is None

    def test_suspend_is_idempotent(self, provisioned_bot, fake_transport):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        first = services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)
        again = services.suspend(subscription=first, actor_type=Actor.SYSTEM)
        assert again.suspended_at == first.suspended_at

    def test_suspend_mirrors_to_the_order_and_fires_the_existing_notification(self, provisioned_bot, fake_transport):
        from apps.notifications.models import Notification
        from apps.notifications.services import notify_from_event

        from apps.bots.models import BotFeature
        from apps.features.models import Feature

        BotFeature.objects.create(
            bot=provisioned_bot, feature=Feature.objects.get(slug="owner_notifications"), is_enabled=True
        )

        subscription = Subscription.objects.get(bot=provisioned_bot)
        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)

        provisioned_bot.origin_order.refresh_from_db()
        assert provisioned_bot.origin_order.status == OrderStatus.SUSPENDED.value

        created = notify_from_event(
            "order.suspended",
            {
                "tenant_id": str(provisioned_bot.tenant.public_id),
                "bot_id": str(provisioned_bot.public_id),
                "order_id": "irrelevant",
                "number": provisioned_bot.origin_order.number,
            },
        )
        assert created >= 1
        assert Notification.objects.filter(event_type="order.suspended").exists()


class TestRenew:
    def test_renew_extends_the_period_and_stays_active(self, provisioned_bot, user):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        before = subscription.current_period_end

        updated = services.renew(subscription=subscription, actor_type=Actor.STAFF, user=user)

        assert updated.status == SubscriptionStatus.ACTIVE
        assert updated.current_period_end > before

    def test_renew_reactivates_a_suspended_bot_and_its_webhook(
        self, provisioned_bot, finance_staff, fake_transport
    ):
        from apps.bots.models import BotPlatformInstance

        subscription = Subscription.objects.get(bot=provisioned_bot)
        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)
        instance = provisioned_bot.instances.get(platform="telegram")
        assert instance.status == BotPlatformInstance.Status.SUSPENDED

        fake_transport.calls.clear()
        services.renew(subscription=subscription, actor_type=Actor.STAFF, user=finance_staff)

        provisioned_bot.refresh_from_db()
        instance.refresh_from_db()
        assert provisioned_bot.status == "ACTIVE"
        assert instance.status == BotPlatformInstance.Status.ACTIVE
        assert fake_transport.called("setWebhook")

    def test_renewal_lets_the_bot_answer_the_webhook_again(
        self, provisioned_bot, finance_staff, fake_transport
    ):
        from apps.bot_runtime.context import load_instance

        subscription = Subscription.objects.get(bot=provisioned_bot)
        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)
        instance = provisioned_bot.instances.get(platform="telegram")
        assert load_instance("telegram", str(instance.public_id)) is None

        services.renew(subscription=subscription, actor_type=Actor.STAFF, user=finance_staff)

        assert load_instance("telegram", str(instance.public_id)) is not None

    def test_renew_clears_a_grace_period(self, provisioned_bot, finance_staff):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        services.enter_grace_period(subscription=subscription)

        updated = services.renew(subscription=subscription, actor_type=Actor.STAFF, user=finance_staff)

        assert updated.status == SubscriptionStatus.ACTIVE
        assert updated.grace_period_ends_at is None


class TestSweep:
    def test_the_sweep_moves_an_expired_subscription_into_grace_period(self, provisioned_bot):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        Subscription.objects.filter(pk=subscription.pk).update(
            current_period_end=timezone.now() - dt.timedelta(hours=1)
        )

        result = sweep_subscriptions()

        subscription.refresh_from_db()
        assert result["entered_grace"] == 1
        assert subscription.status == SubscriptionStatus.GRACE_PERIOD

    def test_the_sweep_suspends_once_the_grace_period_runs_out(self, provisioned_bot, fake_transport):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        Subscription.objects.filter(pk=subscription.pk).update(
            status=SubscriptionStatus.GRACE_PERIOD,
            grace_period_ends_at=timezone.now() - dt.timedelta(hours=1),
        )

        result = sweep_subscriptions()

        subscription.refresh_from_db()
        assert result["suspended"] == 1
        assert subscription.status == SubscriptionStatus.SUSPENDED

    def test_the_sweep_leaves_a_healthy_subscription_alone(self, provisioned_bot):
        result = sweep_subscriptions()
        subscription = Subscription.objects.get(bot=provisioned_bot)
        assert result["entered_grace"] == 0
        assert result["suspended"] == 0
        assert subscription.status == SubscriptionStatus.ACTIVE

    def test_the_sweep_sends_a_renewal_reminder_once_per_threshold(self, provisioned_bot):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        Subscription.objects.filter(pk=subscription.pk).update(
            current_period_end=timezone.now() + dt.timedelta(days=6)
        )

        first = sweep_subscriptions()
        subscription.refresh_from_db()
        assert first["reminders_sent"] == 1
        assert subscription.last_reminder_days == 7

        second = sweep_subscriptions()
        assert second["reminders_sent"] == 0

    def test_the_sweep_is_safe_to_run_with_nothing_due(self, catalogue):
        result = sweep_subscriptions()
        assert result == {"entered_grace": 0, "suspended": 0, "reminders_sent": 0}


class TestSubscriptionAdmin:
    """The confirm-then-POST screens `apps.subscriptions.admin` adds (spec's "admin
    manual management") — same shape as `test_admin_operations.py`'s payment-review checks."""

    @pytest.fixture
    def admin_client_(self, client, db):
        from apps.accounts.models import StaffRole, User, UserStaffRole

        staff = User.objects.create_superuser(email="ops2@example.com", password="TestPassw0rd!23")
        UserStaffRole.objects.create(user=staff, role=StaffRole.SUPER_ADMIN)
        client.force_login(staff)
        return client

    def test_the_suspend_confirm_screen_loads(self, admin_client_, provisioned_bot):
        from django.urls import reverse

        subscription = Subscription.objects.get(bot=provisioned_bot)
        response = admin_client_.get(
            reverse("admin:subscriptions_subscription_suspend", args=[subscription.pk])
        )
        assert response.status_code == 200

    def test_posting_to_suspend_actually_suspends(self, admin_client_, provisioned_bot, fake_transport):
        from django.urls import reverse

        subscription = Subscription.objects.get(bot=provisioned_bot)
        response = admin_client_.post(
            reverse("admin:subscriptions_subscription_suspend", args=[subscription.pk]),
            {"reason": "ops test"},
        )
        assert response.status_code == 302
        subscription.refresh_from_db()
        assert subscription.status == SubscriptionStatus.SUSPENDED

    def test_the_renew_confirm_screen_loads(self, admin_client_, provisioned_bot):
        from django.urls import reverse

        subscription = Subscription.objects.get(bot=provisioned_bot)
        response = admin_client_.get(
            reverse("admin:subscriptions_subscription_renew", args=[subscription.pk])
        )
        assert response.status_code == 200

    def test_posting_to_renew_actually_renews(self, admin_client_, provisioned_bot, fake_transport):
        from django.urls import reverse

        subscription = Subscription.objects.get(bot=provisioned_bot)
        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)

        response = admin_client_.post(
            reverse("admin:subscriptions_subscription_renew", args=[subscription.pk])
        )
        assert response.status_code == 302
        subscription.refresh_from_db()
        assert subscription.status == SubscriptionStatus.ACTIVE

    def test_it_requires_staff(self, client, provisioned_bot):
        from django.urls import reverse

        subscription = Subscription.objects.get(bot=provisioned_bot)
        response = client.get(
            reverse("admin:subscriptions_subscription_suspend", args=[subscription.pk])
        )
        assert response.status_code in (302, 403)


class TestBotSerializerSubscriptionField:
    def test_the_dashboard_shows_the_subscription(self, auth_client, provisioned_bot):
        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/")
        assert response.status_code == 200
        body = response.json()["subscription"]
        assert body["status"] == "ACTIVE"
        assert "formatted" in body["monthly_amount"]

    def test_a_suspended_bot_shows_suspended(self, auth_client, provisioned_bot, fake_transport):
        subscription = Subscription.objects.get(bot=provisioned_bot)
        services.suspend(subscription=subscription, actor_type=Actor.SYSTEM)

        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/")
        assert response.json()["subscription"]["status"] == "SUSPENDED"
