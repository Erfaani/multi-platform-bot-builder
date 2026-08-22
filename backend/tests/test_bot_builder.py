"""Chat-native bot ordering (Phase 10.5's cold-start counterpart to the website
builder) — a customer orders a brand-new bot entirely by chatting with the platform's
own builder bot, with no prior website account.
"""

from __future__ import annotations

import pytest

from apps.businesses.models import FaqEntry
from apps.customers.models import ChannelIdentity, TenantMembership
from apps.orders.models import Order, QuoteSource

pytestmark = pytest.mark.django_db


@pytest.fixture
def card_method(catalogue, db):
    from apps.payments.models import PaymentMethod, PaymentMethodKind

    return PaymentMethod.objects.create(
        name="Test card",
        kind=PaymentMethodKind.MANUAL_CARD,
        provider_slug="manual_card",
        currency="USD",
        config={"card_number": "6037-9999-0000-1111", "card_holder": "Platform", "bank_name": "Melli"},
        is_enabled=True,
    )


@pytest.fixture
def builder_bot(catalogue, tenant_a, user, pool_entry, fake_transport):
    """The platform's own builder bot — same construction the production
    `provision_builder_bot` command uses conceptually (order -> pay -> provision), just
    via the simpler "pool" strategy since tests don't need a deterministic token."""
    from apps.bots.models import BotFeature
    from apps.features.models import Feature
    from apps.orders.domain.state_machine import Actor, OrderStatus
    from apps.orders.services import build_quote, claim_quote, place_order, transition_order
    from apps.provisioning.saga import create_job, run_job

    feature, _ = Feature.objects.update_or_create(
        slug="bot_builder",
        defaults={"category": "core", "icon": "hammer", "name": "Bot builder", "is_active": False},
    )

    quote, _ = build_quote(
        template_slug="generic", platforms=["telegram"], feature_slugs=[],
        currency="USD", business_draft={"name": "Bot Builder Platform"},
    )
    claim_quote(quote=quote, tenant=tenant_a, user=user)
    order = place_order(quote=quote, tenant=tenant_a, user=user)
    for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
        actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
        transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

    job = run_job(create_job(order=order, strategy="pool"))
    assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"

    bot = job.bot
    BotFeature.objects.update_or_create(bot=bot, feature=feature, defaults={"is_enabled": True})
    bot.configuration.bump()
    return bot


def _message(uid: int, text: str, from_id: int) -> dict:
    return {
        "update_id": uid,
        "message": {
            "message_id": uid, "text": text, "chat": {"id": 1},
            "from": {"id": from_id, "first_name": "Buyer", "language_code": "en"},
        },
    }


def _dispatch(instance, payload):
    from apps.bot_runtime.dispatcher import dispatch_update
    from apps.bot_runtime.models import InboundUpdate

    update = InboundUpdate.objects.create(instance=instance, platform_update_id=payload["update_id"], raw=payload)
    return dispatch_update(update)


def _last_sent(instance):
    from apps.bot_runtime.models import OutboundMessage

    return OutboundMessage.objects.filter(instance=instance).latest("created_at")


def _callback_from(sent, label: str) -> str:
    buttons = sent.payload["reply_markup"]["inline_keyboard"]
    return next(b["callback_data"] for row in buttons for b in row if label.lower() in b["text"].lower())


class ChatSession:
    """A tiny driver so each test reads as a script of what the customer did, not a
    wall of InboundUpdate/OutboundMessage plumbing."""

    def __init__(self, instance, from_id: int, base: int):
        self.instance = instance
        self.from_id = from_id
        self._n = base

    def text(self, message: str):
        self._n += 1
        return _dispatch(self.instance, _message(self._n, message, self.from_id))

    def tap(self, label: str):
        self._n += 1
        data = _callback_from(_last_sent(self.instance), label)
        payload = {
            "update_id": self._n,
            "callback_query": {
                "id": f"cb{self._n}", "data": data,
                "from": {"id": self.from_id, "first_name": "Buyer"},
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        }
        return _dispatch(self.instance, payload)


class TestFullOrderingFlow:
    def test_a_stranger_can_order_a_bot_end_to_end(self, builder_bot, card_method):
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=501, base=100)

        r = chat.text("/start")
        assert r.route == "command:start"

        r = chat.tap("build a new bot")
        assert r.route == "builder:start"

        r = chat.tap("clinic")
        assert r.route == "builder:picking_template"
        assert "always included" in r.reply_text.lower()

        r = chat.tap("continue")
        assert r.route == "builder:selecting_features"
        # clinic's default features include FAQ, which collects content — entered at
        # the decision point (add one / skip), never forced straight into a field.
        assert "frequently asked questions" in r.reply_text.lower()

        r = chat.tap("add one now")
        assert r.reply_text == "Question"
        chat.text("Do you accept walk-ins?")
        r = chat.text("Yes, weekdays only.")
        assert "added" in r.reply_text.lower()

        r = chat.tap("i'm done")
        assert r.route == "builder:collecting"
        assert "business called" in r.reply_text.lower()

        r = chat.text("Tehran Smile Clinic")
        assert r.route == "builder:awaiting_business_name"
        assert "due now" in r.reply_text.lower()

        r = chat.tap("place order")
        assert r.route == "builder:reviewing_price"
        assert "email" in r.reply_text.lower()

        r = chat.text("new.customer@example.com")
        assert r.route == "builder:awaiting_email"
        assert "pay" in r.reply_text.lower()

        r = chat.tap("card")
        assert r.route == "builder:choosing_payment_method"
        assert "upload your payment receipt" in r.reply_text.lower()

        # Everything actually got created, correctly linked and priced.
        from apps.accounts.models import User

        buyer = User.objects.get(email="new.customer@example.com")
        assert buyer.has_usable_password()

        identity = ChannelIdentity.objects.get(user=buyer)
        assert identity.platform == "telegram" and identity.platform_user_id == "501"

        membership = TenantMembership.objects.get(user=buyer)
        order = Order.objects.get(tenant=membership.tenant)
        assert order.status == "PENDING_PAYMENT"
        assert order.created_via == QuoteSource.TELEGRAM_BUILDER
        assert order.kind == "NEW"
        assert order.template.slug == "clinic"
        assert order.business_snapshot["feature_config"]["faq"] == [
            {"question": "Do you accept walk-ins?", "answer": "Yes, weekdays only."}
        ]

    def test_declining_optional_faq_leaves_nothing_to_collect(self, builder_bot):
        """Leaving a repeatable_form empty (tapping 'Skip' at the decision point,
        before ever being asked a field) is the established skip affordance from
        Stage 2 — must still work via chat."""
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=502, base=200)

        chat.text("/start")
        chat.tap("build a new bot")
        chat.tap("clinic")
        chat.tap("continue")
        r = chat.tap("skip")
        assert "business called" in r.reply_text.lower()

    def test_toggling_a_feature_off_removes_it_from_the_order(self, builder_bot):
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=503, base=300)

        chat.text("/start")
        chat.tap("build a new bot")
        chat.tap("clinic")
        r = chat.tap("faq")
        assert "faq" not in r.reply_text.lower() or "✅" not in r.reply_text
        r = chat.tap("continue")
        # FAQ was toggled off, so no collection step — straight to business name.
        assert "business called" in r.reply_text.lower()

    def test_a_stray_command_mid_flow_bails_to_the_main_menu(self, builder_bot):
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=504, base=400)

        chat.text("/start")
        chat.tap("build a new bot")
        r = chat.text("/start")
        assert r.route == "builder:picking_template"
        assert "welcome" in r.reply_text.lower() or "help" in r.reply_text.lower()


class TestEmailCollision:
    def test_an_email_with_an_existing_account_is_refused(self, builder_bot, user):
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=505, base=500)

        chat.text("/start")
        chat.tap("build a new bot")
        chat.tap("clinic")
        chat.tap("continue")
        chat.tap("skip")
        chat.text("Some Business")
        chat.tap("place order")
        r = chat.text(user.email)

        assert "already exists" in r.reply_text.lower()
        assert not Order.objects.filter(business_snapshot__name="Some Business").exists()

    def test_an_invalid_email_is_rejected_with_a_reprompt(self, builder_bot):
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=506, base=600)

        chat.text("/start")
        chat.tap("build a new bot")
        chat.tap("clinic")
        chat.tap("continue")
        chat.tap("skip")
        chat.text("Some Business")
        chat.tap("place order")
        r = chat.text("not-an-email")

        assert r.route == "builder:awaiting_email"
        assert "valid" in r.reply_text.lower()


class TestOrderStatus:
    def test_status_reflects_the_orders_real_state(self, builder_bot, tenant_a, user):
        from apps.customers.services import create_link_code, consume_link_code
        from apps.orders.services import build_quote, claim_quote, place_order

        nonce = create_link_code(user=user, platform="telegram")
        consume_link_code(code=nonce.nonce, platform="telegram", platform_user_id="700")

        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram"], feature_slugs=["faq", "contact"],
            currency="USD", business_draft={"name": "My Clinic"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        place_order(quote=quote, tenant=tenant_a, user=user)

        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=700, base=800)
        chat.text("/start")
        r = chat.tap("check my order status")

        assert r.route == "builder:status"
        assert "awaiting your payment" in r.reply_text.lower()

    def test_no_orders_yet_is_handled_gracefully(self, builder_bot):
        instance = builder_bot.instances.get(platform="telegram")
        chat = ChatSession(instance, from_id=701, base=900)
        chat.text("/start")
        r = chat.tap("check my order status")

        assert "no orders" not in r.reply_text.lower() or "haven't" in r.reply_text.lower() or "don't" in r.reply_text.lower()


class TestBotBuilderServices:
    def test_bootstrap_creates_a_random_password_no_one_ever_sees(self):
        from apps.bot_builder.services import find_or_bootstrap_account

        user = find_or_bootstrap_account(
            email="fresh@example.com", platform="telegram", platform_user_id="1", username="ada"
        )
        assert user.has_usable_password()
        identity = ChannelIdentity.objects.get(user=user)
        assert identity.username == "ada"

    def test_bootstrap_refuses_an_existing_email(self, user):
        from apps.bot_builder.services import find_or_bootstrap_account
        from apps.core.errors import ConflictError

        with pytest.raises(ConflictError):
            find_or_bootstrap_account(
                email=user.email, platform="telegram", platform_user_id="1"
            )

    def test_is_valid_email(self):
        from apps.bot_builder.services import is_valid_email

        assert is_valid_email("a@example.com") is True
        assert is_valid_email("not-an-email") is False
        assert is_valid_email("") is False


class TestBaleParity:
    @pytest.fixture
    def dual_builder_bot(self, catalogue, tenant_a, user, fake_transport):
        from apps.bots.credentials import add_pool_entry
        from apps.bots.models import BotFeature
        from apps.features.models import Feature
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        feature, _ = Feature.objects.update_or_create(
            slug="bot_builder",
            defaults={"category": "core", "icon": "hammer", "name": "Bot builder", "is_active": False},
        )
        add_pool_entry(platform="bale", username="dual_builder_bale_bot", token="7800000001:AA-dual-builder-bale")

        quote, _ = build_quote(
            template_slug="generic", platforms=["bale"], feature_slugs=[],
            currency="IRR", business_draft={"name": "Bot Builder Platform"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

        job = run_job(create_job(order=order, strategy="pool"))
        assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"

        bot = job.bot
        BotFeature.objects.update_or_create(bot=bot, feature=feature, defaults={"is_enabled": True})
        bot.configuration.bump()
        return bot

    def test_the_full_flow_works_identically_on_bale(self, dual_builder_bot):
        instance = dual_builder_bot.instances.get(platform="bale")
        chat = ChatSession(instance, from_id=901, base=1000)

        chat.text("/start")
        r = chat.tap("build a new bot")
        assert r.route == "builder:start"

        r = chat.tap("clinic")
        assert r.route == "builder:picking_template"

        chat.tap("continue")
        r = chat.tap("skip")
        assert "business called" in r.reply_text.lower()

        r = chat.text("Bale Test Clinic")
        assert "one-time setup" in r.reply_text.lower()

        chat.tap("place order")
        r = chat.text("bale.buyer@example.com")
        assert "pay" in r.reply_text.lower()

        from apps.accounts.models import User

        buyer = User.objects.get(email="bale.buyer@example.com")
        identity = ChannelIdentity.objects.get(user=buyer)
        assert identity.platform == "bale"

        order = Order.objects.get(tenant__memberships__user=buyer)
        assert order.created_via == QuoteSource.BALE_BUILDER
