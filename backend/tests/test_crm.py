"""CRM: lead capture, feedback, and the owner-notification/broadcast features that
gate on top of them (Phase 7's CRM module)."""

from __future__ import annotations

import pytest

from apps.crm import services
from apps.crm.models import Feedback, Lead, LeadSource, LeadStatus
from apps.core.errors import PermissionDeniedError, ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def contact(provisioned_bot):
    from apps.bot_runtime.models import BusinessContact

    return BusinessContact.objects.create(
        tenant=provisioned_bot.tenant, bot=provisioned_bot, platform="telegram", platform_user_id="555"
    )


class TestLeadServices:
    def test_create_lead_from_contact_form(self, provisioned_bot, contact):
        lead = services.create_lead(
            bot=provisioned_bot, contact=contact, source=LeadSource.CONTACT_FORM, message="Hi there"
        )
        assert lead.status == LeadStatus.NEW
        assert lead.message == "Hi there"

    def test_update_status(self, provisioned_bot, contact, user):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        updated = services.update_lead(bot=provisioned_bot, lead_id=lead.public_id, actor=user, status=LeadStatus.WON)
        assert updated.status == LeadStatus.WON

    def test_an_invalid_status_is_rejected(self, provisioned_bot, contact, user):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        with pytest.raises(ValidationError):
            services.update_lead(bot=provisioned_bot, lead_id=lead.public_id, actor=user, status="NOT_REAL")

    def test_add_note(self, provisioned_bot, contact, user):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        note = services.add_note(bot=provisioned_bot, lead_id=lead.public_id, actor=user, body="Called back")
        assert note.body == "Called back"
        assert lead.notes.count() == 1

    def test_an_empty_note_is_rejected(self, provisioned_bot, contact, user):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        with pytest.raises(ValidationError):
            services.add_note(bot=provisioned_bot, lead_id=lead.public_id, actor=user, body="   ")

    def test_tag_lead(self, provisioned_bot, contact, user):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        services.tag_lead(bot=provisioned_bot, lead_id=lead.public_id, actor=user, tag_name="hot")
        assert list(lead.tags.values_list("name", flat=True)) == ["hot"]

    def test_tagging_twice_reuses_the_tag(self, provisioned_bot, contact, user):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        services.tag_lead(bot=provisioned_bot, lead_id=lead.public_id, actor=user, tag_name="hot")
        services.tag_lead(bot=provisioned_bot, lead_id=lead.public_id, actor=user, tag_name="hot")
        assert lead.tags.count() == 1


class TestFeedbackServices:
    def test_record_feedback(self, provisioned_bot, contact):
        feedback = services.record_feedback(bot=provisioned_bot, contact=contact, rating=5, comment="Great!")
        assert feedback.rating == 5

    def test_rating_must_be_in_range(self, provisioned_bot, contact):
        with pytest.raises(ValidationError):
            services.record_feedback(bot=provisioned_bot, contact=contact, rating=6)


class TestCrmConversation:
    """The full customer-facing flow, through the real dispatcher."""

    @pytest.fixture
    def crm_bot(self, catalogue, tenant_a, user, pool_entry, fake_transport):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug="generic", platforms=["telegram"],
            feature_slugs=["contact_request", "consultation_request", "feedback"],
            currency="USD", business_draft={"name": "Generic Biz"},
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

    def _message(self, update_id, text, user_id="777"):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id, "text": text, "chat": {"id": 1},
                "from": {"id": int(user_id), "first_name": "Ada", "username": "ada", "language_code": "en"},
            },
        }

    def _callback_from(self, sent, label: str) -> str:
        buttons = sent.payload["reply_markup"]["inline_keyboard"]
        return next(b["callback_data"] for row in buttons for b in row if b["text"] == label)

    def _last_sent(self, instance):
        from apps.bot_runtime.models import OutboundMessage

        return OutboundMessage.objects.filter(instance=instance).latest("created_at")

    def test_contact_request_captures_a_free_text_message(self, crm_bot, fake_transport):
        instance = crm_bot.instances.get(platform="telegram")

        started = self._dispatch(instance, self._message(1, "/contactus"))
        assert started.route == "command:contactus"

        result = self._dispatch(instance, self._message(2, "I have a question about pricing."))
        assert result.route == "crm:awaiting_message"

        lead = Lead.objects.get(bot=crm_bot)
        assert lead.source == LeadSource.CONTACT_FORM
        assert lead.message == "I have a question about pricing."

    def test_a_command_mid_flow_bails_out_to_the_main_menu_without_capturing_it(self, crm_bot, fake_transport):
        """`/menu` mid-flow is still routed to the *state* handler (that's how a
        non-idle session always resolves) — the bail-out is `capture_message` itself
        recognising a stray command and resetting, not the router doing it."""
        instance = crm_bot.instances.get(platform="telegram")
        self._dispatch(instance, self._message(10, "/contactus"))

        result = self._dispatch(instance, self._message(11, "/menu"))
        assert result.route == "crm:awaiting_message"
        assert "Generic Biz" in result.reply_text
        assert not Lead.objects.filter(bot=crm_bot).exists()

    def test_consultation_request_validates_the_phone(self, crm_bot, fake_transport):
        instance = crm_bot.instances.get(platform="telegram")
        self._dispatch(instance, self._message(20, "/consultation"))

        rejected = self._dispatch(instance, self._message(21, "not a phone"))
        assert rejected.route == "crm:awaiting_phone"
        assert not Lead.objects.filter(bot=crm_bot).exists()

        accepted = self._dispatch(instance, self._message(22, "+1 555 010 0100"))
        assert accepted.route == "crm:awaiting_phone"
        lead = Lead.objects.get(bot=crm_bot)
        assert lead.source == LeadSource.CONSULTATION_REQUEST
        assert lead.phone == "+1 555 010 0100"

    def test_feedback_is_a_single_button_tap(self, crm_bot, fake_transport):
        instance = crm_bot.instances.get(platform="telegram")
        self._dispatch(instance, self._message(30, "/feedback"))
        pick_five = self._callback_from(self._last_sent(instance), "⭐⭐⭐⭐⭐")

        result = self._dispatch(instance, {
            "update_id": 31,
            "callback_query": {"id": "cb", "data": pick_five, "from": {"id": 777, "first_name": "Ada"}, "message": {"message_id": 1, "chat": {"id": 1}}},
        })
        assert result.route == "feedback:rate"
        feedback = Feedback.objects.get(bot=crm_bot)
        assert feedback.rating == 5


class TestOwnerNotificationsGating:
    def test_a_lead_notifies_the_owner_when_the_feature_is_bought(self, provisioned_bot, contact, user):
        from apps.features.models import Feature
        from apps.bots.models import BotFeature
        from apps.notifications.models import Notification

        feature = Feature.objects.get(slug="owner_notifications")
        BotFeature.objects.create(bot=provisioned_bot, feature=feature, is_enabled=True)

        services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.CONTACT_FORM, message="hi")

        from apps.core.events import publish
        # publish() enqueues via the outbox; call the consumer directly to keep this a
        # unit test of the gating logic rather than a round trip through the relay.
        from apps.notifications.services import notify_from_event

        created = notify_from_event(
            "crm.lead_captured",
            {"tenant_id": str(provisioned_bot.tenant.public_id), "bot_id": str(provisioned_bot.public_id), "dedupe_key": "lead:test-1", "source": "Contact form"},
        )
        assert created >= 1
        assert Notification.objects.filter(event_type="crm.lead_captured").exists()

    def test_a_lead_does_not_notify_without_the_feature(self, provisioned_bot):
        from apps.notifications.services import notify_from_event

        created = notify_from_event(
            "crm.lead_captured",
            {"tenant_id": str(provisioned_bot.tenant.public_id), "bot_id": str(provisioned_bot.public_id), "dedupe_key": "lead:test-2", "source": "Contact form"},
        )
        assert created == 0


class TestBroadcast:
    def test_broadcast_requires_the_feature(self, provisioned_bot, user):
        from apps.notifications.broadcast import send_broadcast

        with pytest.raises(PermissionDeniedError):
            send_broadcast(bot=provisioned_bot, actor=user, text="Hello everyone")

    def test_broadcast_counts_active_contacts(self, provisioned_bot, contact, user):
        from apps.bots.models import BotFeature
        from apps.features.models import Feature
        from apps.notifications.broadcast import send_broadcast

        feature = Feature.objects.get(slug="customer_broadcast")
        BotFeature.objects.create(bot=provisioned_bot, feature=feature, is_enabled=True)

        recipients = send_broadcast(bot=provisioned_bot, actor=user, text="Hello everyone")
        assert recipients == 1

    def test_an_empty_broadcast_is_rejected(self, provisioned_bot, user):
        from apps.bots.models import BotFeature
        from apps.features.models import Feature
        from apps.notifications.broadcast import send_broadcast

        feature = Feature.objects.get(slug="customer_broadcast")
        BotFeature.objects.create(bot=provisioned_bot, feature=feature, is_enabled=True)

        with pytest.raises(ValidationError):
            send_broadcast(bot=provisioned_bot, actor=user, text="   ")


class TestCrmApi:
    def test_lead_list_update_note_and_tag(self, auth_client, provisioned_bot, contact):
        lead = services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/leads/")
        assert listed.status_code == 200
        assert any(item["id"] == str(lead.public_id) for item in listed.json())

        updated = auth_client.patch(
            f"/api/v1/bots/{provisioned_bot.public_id}/leads/{lead.public_id}/",
            {"status": "WON"}, format="json",
        )
        assert updated.status_code == 200 and updated.json()["status"] == "WON"

        noted = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/leads/{lead.public_id}/notes/",
            {"body": "Followed up"}, format="json",
        )
        assert noted.status_code == 201
        assert len(noted.json()["notes"]) == 1

        tagged = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/leads/{lead.public_id}/tags/",
            {"tag": "hot"}, format="json",
        )
        assert tagged.status_code == 201
        assert tagged.json()["tags"] == ["hot"]

    def test_feedback_list(self, auth_client, provisioned_bot, contact):
        services.record_feedback(bot=provisioned_bot, contact=contact, rating=4)

        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/feedback/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_a_stranger_cannot_see_another_tenants_leads(self, other_client, provisioned_bot, contact):
        services.create_lead(bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL)
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/leads/")
        assert response.status_code == 404

    def test_broadcast_endpoint(self, auth_client, provisioned_bot, contact):
        from apps.bots.models import BotFeature
        from apps.features.models import Feature

        feature = Feature.objects.get(slug="customer_broadcast")
        BotFeature.objects.create(bot=provisioned_bot, feature=feature, is_enabled=True)

        response = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/broadcast/",
            {"text": "We're open this weekend!"}, format="json",
        )
        assert response.status_code == 200
        assert response.json()["recipients"] == 1
