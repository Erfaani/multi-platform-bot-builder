"""Telegram Mini App — end-user storefront/booking surface (Phase 10.5)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from apps.core.errors import PermissionDeniedError
from apps.miniapp.services import verify_init_data

pytestmark = pytest.mark.django_db

TOKEN = "7100000001:AA-dual-clinic-telegram-token-aaaaaaaaaaaa"


def _make_init_data(*, token: str = TOKEN, user: dict | None = None, auth_date: int | None = None) -> str:
    user = user or {"id": 555, "first_name": "Ada", "username": "ada", "language_code": "en"}
    fields = {
        "query_id": "AAH_test",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class TestVerifyInitData:
    def test_a_correctly_signed_payload_verifies(self, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        user = verify_init_data(instance=instance, raw_init_data=_make_init_data())
        assert user["id"] == 555
        assert user["username"] == "ada"

    def test_a_tampered_payload_is_rejected(self, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        raw = _make_init_data().replace("Ada", "Eve")
        with pytest.raises(PermissionDeniedError):
            verify_init_data(instance=instance, raw_init_data=raw)

    def test_signed_with_the_wrong_bots_token_is_rejected(self, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        raw = _make_init_data(token="9999999999:AA-someone-elses-token-zzzzzzzzzzzz")
        with pytest.raises(PermissionDeniedError):
            verify_init_data(instance=instance, raw_init_data=raw)

    def test_stale_init_data_is_rejected(self, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        raw = _make_init_data(auth_date=int(time.time()) - 2 * 86400)
        with pytest.raises(PermissionDeniedError):
            verify_init_data(instance=instance, raw_init_data=raw)

    def test_missing_hash_is_rejected(self, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        with pytest.raises(PermissionDeniedError):
            verify_init_data(instance=instance, raw_init_data="user=%7B%7D&auth_date=1")


@pytest.fixture
def dual_provisioned_bot(catalogue, tenant_a, user, fake_transport):
    """A bot with both an appointment feature and a Telegram instance whose token
    matches `TOKEN` above (`conftest_bots.TOKEN_IDENTITIES` maps this prefix to a real
    identity `fake_transport`'s `getMe` will answer for)."""
    from apps.bots.credentials import add_pool_entry
    from apps.orders.domain.state_machine import Actor, OrderStatus
    from apps.orders.services import build_quote, claim_quote, place_order, transition_order
    from apps.provisioning.saga import create_job, run_job

    add_pool_entry(platform="telegram", username="dual_clinic_tg_bot", token=TOKEN)

    quote, _ = build_quote(
        template_slug="clinic", platforms=["telegram"], feature_slugs=["faq", "appointment"],
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


class TestMiniAppContentApi:
    def _url(self, instance, suffix: str) -> str:
        return f"/api/v1/miniapp/{instance.public_id}/{suffix}"

    def test_content_reflects_enabled_features(self, api, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        response = api.post(self._url(instance, "content/"), {"init_data": _make_init_data()}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["bot_name"] == "Tehran Smile Clinic"
        assert "faq" in body
        assert "appointment_services" in body
        assert "products" not in body  # product_catalog was never enabled

    def test_a_bad_signature_is_refused(self, api, dual_provisioned_bot):
        instance = dual_provisioned_bot.instances.get(platform="telegram")
        response = api.post(
            self._url(instance, "content/"), {"init_data": "user=x&auth_date=1&hash=deadbeef"}, format="json"
        )
        assert response.status_code == 403

    def test_an_inactive_instance_is_not_found(self, api, dual_provisioned_bot):
        response = api.post(
            f"/api/v1/miniapp/{'0' * 8}-0000-0000-0000-{'0' * 12}/content/",
            {"init_data": _make_init_data()}, format="json",
        )
        assert response.status_code == 404

    def test_slots_and_booking(self, api, dual_provisioned_bot):
        from datetime import time as dt_time

        from apps.appointments import services as appointment_services
        from apps.businesses.models import WorkingHours

        service = appointment_services.create_service(
            bot=dual_provisioned_bot, actor=None, name="Cleaning", duration_minutes=30
        )
        staff = appointment_services.get_or_create_default_staff(dual_provisioned_bot)
        WorkingHours.objects.create(
            tenant=dual_provisioned_bot.tenant, bot=dual_provisioned_bot, weekday=0,
            opens_at=dt_time(9, 0), closes_at=dt_time(17, 0),
        )

        instance = dual_provisioned_bot.instances.get(platform="telegram")
        from datetime import timedelta

        from django.utils import timezone as dj_timezone

        next_monday = dj_timezone.now().date()
        while next_monday.weekday() != 0:
            next_monday += timedelta(days=1)

        slots_response = api.post(
            self._url(instance, "appointment-slots/"),
            {
                "init_data": _make_init_data(), "service": service.pk, "staff": staff.pk,
                "date": next_monday.isoformat(),
            },
            format="json",
        )
        assert slots_response.status_code == 200
        slots = slots_response.json()
        assert len(slots) > 0

        book_response = api.post(
            self._url(instance, "book/"),
            {
                "init_data": _make_init_data(), "service": service.pk, "staff": staff.pk,
                "starts_at": slots[0]["starts_at"],
            },
            format="json",
        )
        assert book_response.status_code == 201

        from apps.appointments.models import Appointment
        from apps.bot_runtime.models import BusinessContact

        contact = BusinessContact.objects.get(bot=dual_provisioned_bot, platform_user_id="555")
        assert Appointment.objects.filter(bot=dual_provisioned_bot, contact=contact).exists()


@pytest.fixture
def dual_clinic_bot(catalogue, tenant_a, user, fake_transport):
    """A bot with both a Telegram and a Bale instance, to check `core:open_app`
    degrades correctly on the platform that cannot open a Mini App."""
    from apps.bots.credentials import add_pool_entry
    from apps.orders.domain.state_machine import Actor, OrderStatus
    from apps.orders.services import build_quote, claim_quote, place_order, transition_order
    from apps.provisioning.saga import create_job, run_job

    add_pool_entry(platform="telegram", username="dual_clinic_tg_bot", token="7100000001:AA-dual-clinic-tg")
    add_pool_entry(platform="bale", username="dual_clinic_bale_bot", token="7200000001:AA-dual-clinic-bale")

    quote, _ = build_quote(
        template_slug="clinic", platforms=["telegram", "bale"], feature_slugs=["faq"],
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


class TestOpenAppHandler:
    def _dispatch(self, instance, uid: int, from_id: int, text: str):
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate

        payload = {
            "update_id": uid,
            "message": {
                "message_id": uid, "text": text, "chat": {"id": 1},
                "from": {"id": from_id, "first_name": "Ada", "language_code": "en"},
            },
        }
        update = InboundUpdate.objects.create(instance=instance, platform_update_id=uid, raw=payload)
        return dispatch_update(update)

    def test_telegram_gets_a_launch_button(self, provisioned_bot):
        instance = provisioned_bot.instances.get(platform="telegram")
        self._dispatch(instance, 1, 601, "/menu")
        result = self._dispatch(instance, 2, 601, "/menu")
        # Reaching the handler directly (no menu-label parsing needed for this check):
        from apps.bot_runtime.context import resolve_context
        from apps.businesses.handlers import open_app

        ctx = resolve_context(instance)
        outcome = open_app(None, session=None, ctx=ctx, value="", locale="en")
        assert outcome.reply.choices[0].web_app_url is not None
        assert outcome.reply.choices[0].web_app_url.endswith(f"/miniapp/{instance.public_id}")

    def test_bale_is_told_its_not_available(self, dual_clinic_bot):
        from apps.bot_runtime.context import resolve_context
        from apps.businesses.handlers import open_app

        instance = dual_clinic_bot.instances.get(platform="bale")
        ctx = resolve_context(instance)
        outcome = open_app(None, session=None, ctx=ctx, value="", locale="en")
        # No web_app_url on any choice — and the customer still gets the normal menu
        # back rather than a dead end.
        assert all(choice.web_app_url is None for choice in outcome.reply.choices)
        assert outcome.reply.text_key == "bot.miniapp.unavailable"
