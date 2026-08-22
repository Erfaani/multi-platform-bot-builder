"""Cross-channel identity linking (spec §47) and the owner admin menu it unlocks
(Phase 10.5's hybrid model: simple/frequent tasks in the bot, everything else on the
website)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone as dj_timezone

from apps.core.errors import NotFoundError
from apps.customers import services as customer_services
from apps.customers.models import ChannelIdentity, IdentityLinkNonce, TenantMembership, TenantRole
from apps.businesses.models import FaqEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def contact(provisioned_bot):
    from apps.bot_runtime.models import BusinessContact

    return BusinessContact.objects.create(
        tenant=provisioned_bot.tenant, bot=provisioned_bot, platform="telegram", platform_user_id="500"
    )


class TestChannelLinkingServices:
    def test_create_link_code_is_short_and_expires_soon(self, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        assert len(nonce.nonce) == customer_services.LINK_CODE_LENGTH
        assert nonce.nonce.isdigit()
        assert nonce.expires_at <= dj_timezone.now() + customer_services.LINK_CODE_TTL

    def test_generating_a_new_code_invalidates_the_old_one(self, user):
        first = customer_services.create_link_code(user=user, platform="telegram")
        customer_services.create_link_code(user=user, platform="telegram")

        first.refresh_from_db()
        assert first.consumed_at is not None
        assert not first.is_usable

    def test_consume_valid_code_creates_a_channel_identity(self, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")

        identity = customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900", username="ada"
        )
        assert identity is not None
        assert identity.user == user
        assert identity.platform_user_id == "900"

        nonce.refresh_from_db()
        assert nonce.consumed_at is not None

    def test_a_code_cannot_be_used_twice(self, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900"
        )

        second_attempt = customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="901"
        )
        assert second_attempt is None

    def test_a_code_only_works_on_the_platform_it_was_issued_for(self, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")

        result = customer_services.consume_link_code(
            code=nonce.nonce, platform="bale", platform_user_id="900"
        )
        assert result is None

    def test_an_expired_code_is_rejected(self, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        nonce.expires_at = dj_timezone.now() - timedelta(seconds=1)
        nonce.save(update_fields=["expires_at"])

        result = customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900"
        )
        assert result is None

    def test_an_unknown_code_is_rejected(self, user):
        result = customer_services.consume_link_code(
            code="000000", platform="telegram", platform_user_id="900"
        )
        assert result is None

    def test_relinking_the_same_platform_account_moves_it_to_the_new_user(self, user, other_user):
        first_nonce = customer_services.create_link_code(user=user, platform="telegram")
        customer_services.consume_link_code(
            code=first_nonce.nonce, platform="telegram", platform_user_id="900"
        )

        second_nonce = customer_services.create_link_code(user=other_user, platform="telegram")
        customer_services.consume_link_code(
            code=second_nonce.nonce, platform="telegram", platform_user_id="900"
        )

        identity = ChannelIdentity.objects.get(platform="telegram", platform_user_id="900")
        assert identity.user == other_user

    def test_resolve_tenant_membership_finds_a_linked_owner(self, user, tenant_a):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900"
        )

        membership = customer_services.resolve_tenant_membership(
            platform="telegram", platform_user_id="900", tenant_id=tenant_a.pk
        )
        assert membership is not None
        assert membership.role == TenantRole.OWNER

    def test_resolve_tenant_membership_is_none_for_an_unlinked_platform_user(self, tenant_a):
        membership = customer_services.resolve_tenant_membership(
            platform="telegram", platform_user_id="999999", tenant_id=tenant_a.pk
        )
        assert membership is None

    def test_unlink_removes_the_identity(self, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        identity = customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900"
        )
        customer_services.unlink_channel_identity(user=user, identity_id=identity.pk)
        assert not ChannelIdentity.objects.filter(pk=identity.pk).exists()

    def test_a_stranger_cannot_unlink_someone_elses_identity(self, user, other_user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        identity = customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900"
        )
        with pytest.raises(NotFoundError):
            customer_services.unlink_channel_identity(user=other_user, identity_id=identity.pk)


class TestChannelLinkApi:
    def test_owner_can_generate_and_list_a_code(self, auth_client):
        created = auth_client.post("/api/v1/channel-links/", {"platform": "telegram"}, format="json")
        assert created.status_code == 201
        assert len(created.json()["code"]) == 6

    def test_unauthenticated_is_rejected(self, api):
        response = api.post("/api/v1/channel-links/", {"platform": "telegram"}, format="json")
        assert response.status_code == 401

    def test_list_and_unlink(self, auth_client, user):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        identity = customer_services.consume_link_code(
            code=nonce.nonce, platform="telegram", platform_user_id="900"
        )

        listed = auth_client.get("/api/v1/channel-links/")
        assert listed.status_code == 200
        assert any(row["id"] == identity.pk for row in listed.json())

        deleted = auth_client.delete(f"/api/v1/channel-links/{identity.pk}/")
        assert deleted.status_code == 204
        assert not ChannelIdentity.objects.filter(pk=identity.pk).exists()


class TestOwnerAdminConversation:
    """The full customer-facing flow, through the real dispatcher — Telegram and Bale
    both dispatch through the same `apps.bot_admin.handlers`, so parity is checked once
    explicitly (`test_the_admin_menu_works_identically_on_bale`) rather than per action."""

    @pytest.fixture
    def dual_admin_bot(self, catalogue, tenant_a, user, fake_transport):
        from apps.bots.credentials import add_pool_entry
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        add_pool_entry(
            platform="telegram", username="admin_tg_bot",
            token="7500000001:AA-admin-telegram-token-aaaaaaaaaaaa",
        )
        add_pool_entry(
            platform="bale", username="admin_bale_bot",
            token="7600000001:AA-admin-bale-token-bbbbbbbbbbbbbb",
        )

        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram", "bale"],
            feature_slugs=["faq", "contact", "appointment"],
            currency="USD", business_draft={"name": "Tehran Smile Clinic"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

        job = run_job(create_job(order=order, strategy="pool"))
        assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"
        return job.bot

    def _dispatch(self, instance, payload):
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate

        update = InboundUpdate.objects.create(
            instance=instance, platform_update_id=payload["update_id"], raw=payload
        )
        return dispatch_update(update)

    def _message(self, update_id, text, user_id):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id, "text": text, "chat": {"id": 1},
                "from": {"id": user_id, "first_name": "Ada", "language_code": "en"},
            },
        }

    def _callback_from(self, sent, label: str) -> str:
        buttons = sent.payload["reply_markup"]["inline_keyboard"]
        return next(b["callback_data"] for row in buttons for b in row if b["text"] == label)

    def _last_sent(self, instance):
        from apps.bot_runtime.models import OutboundMessage

        return OutboundMessage.objects.filter(instance=instance).latest("created_at")

    def test_a_stranger_gets_a_polite_refusal(self, provisioned_bot, fake_transport):
        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(1, "/admin", 950))
        assert result.route == "command:admin"
        assert "My Bots" in result.reply_text or "management" in result.reply_text.lower()

    def test_linking_then_admin_shows_the_menu(self, provisioned_bot, user, fake_transport):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        instance = provisioned_bot.instances.get(platform="telegram")

        linked = self._dispatch(instance, self._message(1, f"/link {nonce.nonce}", 951))
        assert "linked" in linked.reply_text.lower()

        menu = self._dispatch(instance, self._message(2, "/admin", 951))
        assert menu.route == "command:admin"
        assert "manage" in menu.reply_text.lower()

    def test_an_invalid_code_is_rejected(self, provisioned_bot, fake_transport):
        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(1, "/link 000000", 952))
        assert "not valid" in result.reply_text.lower() or "expired" in result.reply_text.lower()

    def test_recent_leads_action(self, provisioned_bot, user, contact, fake_transport):
        from apps.crm import services as crm_services
        from apps.crm.models import LeadSource

        crm_services.create_lead(
            bot=provisioned_bot, contact=contact, source=LeadSource.CONTACT_FORM, message="Hi"
        )

        nonce = customer_services.create_link_code(user=user, platform="telegram")
        instance = provisioned_bot.instances.get(platform="telegram")
        self._dispatch(instance, self._message(1, f"/link {nonce.nonce}", 953))
        self._dispatch(instance, self._message(2, "/admin", 953))

        pick_leads = self._callback_from(self._last_sent(instance), "Recent leads")
        result = self._dispatch(instance, {
            "update_id": 3,
            "callback_query": {
                "id": "cb", "data": pick_leads,
                "from": {"id": 953, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        })
        assert result.route == "core:admin_leads"
        assert contact.display_name in result.reply_text or "—" in result.reply_text

    def test_add_faq_creates_a_real_entry(self, provisioned_bot, user, fake_transport):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        instance = provisioned_bot.instances.get(platform="telegram")
        self._dispatch(instance, self._message(1, f"/link {nonce.nonce}", 954))
        self._dispatch(instance, self._message(2, "/admin", 954))

        pick_faq = self._callback_from(self._last_sent(instance), "Add an FAQ")
        started = self._dispatch(instance, {
            "update_id": 3,
            "callback_query": {
                "id": "cb", "data": pick_faq,
                "from": {"id": 954, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        })
        assert started.route == "core:admin_faq_start"

        self._dispatch(instance, self._message(4, "Do you take walk-ins?", 954))
        answered = self._dispatch(instance, self._message(5, "Yes, weekdays only.", 954))
        assert answered.route == "admin:awaiting_faq_answer"

        entry = FaqEntry.objects.get(bot=provisioned_bot)
        assert entry.question == "Do you take walk-ins?"
        assert entry.answer == "Yes, weekdays only."

    def test_a_removed_membership_immediately_loses_admin_access(
        self, provisioned_bot, user, fake_transport
    ):
        nonce = customer_services.create_link_code(user=user, platform="telegram")
        instance = provisioned_bot.instances.get(platform="telegram")
        self._dispatch(instance, self._message(1, f"/link {nonce.nonce}", 955))

        TenantMembership.objects.filter(tenant=provisioned_bot.tenant, user=user).delete()

        result = self._dispatch(instance, self._message(2, "/admin", 955))
        assert "management" in result.reply_text.lower() or "My Bots" in result.reply_text

    def test_the_admin_menu_works_identically_on_bale(self, dual_admin_bot, user):
        nonce = customer_services.create_link_code(user=user, platform="bale")
        instance = dual_admin_bot.instances.get(platform="bale")

        self._dispatch(instance, self._message(1, f"/link {nonce.nonce}", 956))
        menu = self._dispatch(instance, self._message(2, "/admin", 956))

        assert menu.route == "command:admin"
        assert "manage" in menu.reply_text.lower()
