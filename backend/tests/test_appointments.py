"""Appointment booking — Phase 7's first business module (DATABASE.md §9).

`provisioned_bot` (faq + contact, no appointment feature) is enough for the service-layer
and dashboard-API tests below, since neither touches feature gating. The conversational
flow is the one thing that needs a bot that actually bought "appointment", so
`TestBookingConversation` builds its own.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone as dj_timezone

from apps.appointments import services
from apps.appointments.models import Appointment, AppointmentStatus, StaffMember, TimeOff
from apps.businesses.models import WorkingHours
from apps.core.errors import ConflictError, ValidationError

pytestmark = pytest.mark.django_db


def _next_weekday(weekday: int) -> date:
    """The next date (today included) that falls on `weekday` (0=Monday)."""
    today = dj_timezone.now().date()
    offset = (weekday - today.weekday()) % 7
    return today + timedelta(days=offset)


def _open_all_day(bot, weekday: int) -> None:
    WorkingHours.objects.create(
        tenant=bot.tenant, bot=bot, weekday=weekday, opens_at=time(0, 0), closes_at=time(23, 59)
    )


@pytest.fixture
def service(provisioned_bot):
    return services.create_service(
        bot=provisioned_bot, actor=None, name="Cleaning", duration_minutes=30, buffer_minutes=10
    )


@pytest.fixture
def staff(provisioned_bot):
    return services.create_staff(bot=provisioned_bot, actor=None, name="Dr. Ada")


@pytest.fixture
def contact(provisioned_bot):
    from apps.bot_runtime.models import BusinessContact

    return BusinessContact.objects.create(
        tenant=provisioned_bot.tenant, bot=provisioned_bot, platform="telegram", platform_user_id="555"
    )


class TestServiceCrud:
    def test_create_requires_a_name(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_service(bot=provisioned_bot, actor=None, name="  ", duration_minutes=30)

    def test_create_requires_a_positive_duration(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_service(bot=provisioned_bot, actor=None, name="Cleaning", duration_minutes=0)

    def test_update_and_delete(self, provisioned_bot, service):
        updated = services.update_service(
            bot=provisioned_bot, service_id=service.pk, actor=None, name="Deep clean"
        )
        assert updated.name == "Deep clean"

        services.delete_service(bot=provisioned_bot, service_id=service.pk, actor=None)
        assert not services.list_services(provisioned_bot.pk)

    def test_editing_a_service_bumps_the_runtime_cache(self, provisioned_bot, service):
        before = provisioned_bot.configuration.version
        services.update_service(bot=provisioned_bot, service_id=service.pk, actor=None, name="New name")
        provisioned_bot.configuration.refresh_from_db()
        assert provisioned_bot.configuration.version > before


class TestStaffCrud:
    def test_create_requires_a_name(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_staff(bot=provisioned_bot, actor=None, name=" ")

    def test_a_staff_member_with_no_services_performs_everything(self, provisioned_bot, staff, service):
        assert staff.performs(service)

    def test_a_staff_member_with_assigned_services_is_restricted(self, provisioned_bot, staff, service):
        other = services.create_service(bot=provisioned_bot, actor=None, name="Whitening", duration_minutes=45)
        staff.services.set([service])
        staff.refresh_from_db()
        assert staff.performs(service)
        assert not staff.performs(other)

    def test_get_or_create_default_staff_is_idempotent(self, provisioned_bot):
        first = services.get_or_create_default_staff(provisioned_bot)
        second = services.get_or_create_default_staff(provisioned_bot)
        assert first.pk == second.pk

    def test_get_or_create_default_staff_never_leaves_booking_unblocked(self, provisioned_bot):
        assert StaffMember.objects.filter(bot=provisioned_bot).count() == 0
        default = services.get_or_create_default_staff(provisioned_bot)
        assert default.is_active


class TestAvailableSlots:
    def test_slots_only_exist_inside_working_hours(self, provisioned_bot, service, staff):
        day = _next_weekday(0)
        WorkingHours.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, weekday=0,
            opens_at=time(9, 0), closes_at=time(10, 0),
        )
        slots = services.available_slots(
            bot_id=provisioned_bot.pk, timezone="UTC", service=service, staff=staff, day=day
        )
        assert slots
        assert all(s.starts_at.time() >= time(9, 0) for s in slots)
        assert all(s.ends_at.time() <= time(10, 0) for s in slots)

    def test_a_closed_day_has_no_slots(self, provisioned_bot, service, staff):
        day = _next_weekday(0)
        WorkingHours.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, weekday=0, is_closed=True
        )
        assert services.available_slots(
            bot_id=provisioned_bot.pk, timezone="UTC", service=service, staff=staff, day=day
        ) == []

    def test_an_existing_appointment_removes_its_slot(self, provisioned_bot, service, staff, contact):
        day = _next_weekday(0)
        _open_all_day(provisioned_bot, 0)
        starts_at = dj_timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        if starts_at.date() != day:
            starts_at = datetime.combine(day, time(12, 0), tzinfo=dt_timezone.utc)
        # Make sure the slot is far enough in the future to survive MIN_LEAD_MINUTES.
        starts_at = max(starts_at, dj_timezone.now() + timedelta(hours=1))

        services.book_appointment(bot=provisioned_bot, contact=contact, service=service, staff=staff, starts_at=starts_at)

        slots = services.available_slots(
            bot_id=provisioned_bot.pk, timezone="UTC", service=service, staff=staff, day=starts_at.date()
        )
        assert all(s.starts_at != starts_at for s in slots)

    def test_time_off_removes_slots(self, provisioned_bot, service, staff):
        day = _next_weekday(0)
        _open_all_day(provisioned_bot, 0)
        TimeOff.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, staff=staff,
            starts_at=datetime.combine(day, time(0, 0), tzinfo=dt_timezone.utc),
            ends_at=datetime.combine(day, time(23, 59), tzinfo=dt_timezone.utc),
        )
        assert services.available_slots(
            bot_id=provisioned_bot.pk, timezone="UTC", service=service, staff=staff, day=day
        ) == []

    def test_a_staff_member_who_does_not_perform_the_service_is_rejected(self, provisioned_bot, service, staff):
        other = services.create_service(bot=provisioned_bot, actor=None, name="Whitening", duration_minutes=45)
        staff.services.set([other])
        with pytest.raises(ValidationError):
            services.available_slots(
                bot_id=provisioned_bot.pk, timezone="UTC", service=service, staff=staff, day=_next_weekday(0)
            )

    def test_slots_respect_the_buffer(self, provisioned_bot, staff):
        """A 90-minute window fits 3 back-to-back 30-minute slots, or just 1 once a
        40-minute buffer is added — 70 minutes needed per slot leaves no room for a
        second one."""
        service = services.create_service(
            bot=provisioned_bot, actor=None, name="Long buffer", duration_minutes=30, buffer_minutes=40
        )
        day = _next_weekday(0)
        WorkingHours.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, weekday=0,
            opens_at=time(9, 0), closes_at=time(10, 30),
        )
        slots = services.available_slots(
            bot_id=provisioned_bot.pk, timezone="UTC", service=service, staff=staff, day=day
        )
        assert len(slots) == 1


class TestBooking:
    def test_booking_creates_a_confirmed_appointment(self, provisioned_bot, service, staff, contact):
        starts_at = dj_timezone.now() + timedelta(days=1)
        appointment = services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff, starts_at=starts_at
        )
        assert appointment.status == AppointmentStatus.CONFIRMED
        assert appointment.ends_at == starts_at + timedelta(minutes=service.duration_minutes)

    def test_cannot_book_a_service_the_staff_does_not_perform(self, provisioned_bot, staff, contact):
        other = services.create_service(bot=provisioned_bot, actor=None, name="Whitening", duration_minutes=45)
        staff.services.set([other])
        another = services.create_service(bot=provisioned_bot, actor=None, name="Filling", duration_minutes=20)
        with pytest.raises(ValidationError):
            services.book_appointment(
                bot=provisioned_bot, contact=contact, service=another, staff=staff,
                starts_at=dj_timezone.now() + timedelta(days=1),
            )

    def test_cannot_book_in_the_past(self, provisioned_bot, service, staff, contact):
        with pytest.raises(ConflictError):
            services.book_appointment(
                bot=provisioned_bot, contact=contact, service=service, staff=staff,
                starts_at=dj_timezone.now() - timedelta(hours=1),
            )

    def test_the_database_rejects_an_overlapping_booking_even_bypassing_the_service_layer(
        self, provisioned_bot, service, staff, contact
    ):
        """The real guarantee: not "the service layer checks", but "the database refuses"."""
        starts_at = dj_timezone.now() + timedelta(days=1)
        ends_at = starts_at + timedelta(minutes=service.duration_minutes)

        Appointment.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, contact=contact, service=service,
            staff=staff, starts_at=starts_at, ends_at=ends_at, business_timezone="UTC",
            status=AppointmentStatus.CONFIRMED,
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            Appointment.objects.create(
                tenant=provisioned_bot.tenant, bot=provisioned_bot, contact=contact, service=service,
                staff=staff, starts_at=starts_at + timedelta(minutes=10), ends_at=ends_at + timedelta(minutes=10),
                business_timezone="UTC", status=AppointmentStatus.CONFIRMED,
            )

    def test_a_cancelled_appointment_does_not_block_the_slot(self, provisioned_bot, service, staff, contact):
        starts_at = dj_timezone.now() + timedelta(days=1)
        ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        first = Appointment.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, contact=contact, service=service,
            staff=staff, starts_at=starts_at, ends_at=ends_at, business_timezone="UTC",
            status=AppointmentStatus.CONFIRMED,
        )
        services.cancel_appointment(appointment=first, actor=None)

        # The same slot, same staff, is bookable again now that the row is CANCELLED.
        second = Appointment.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, contact=contact, service=service,
            staff=staff, starts_at=starts_at, ends_at=ends_at, business_timezone="UTC",
            status=AppointmentStatus.CONFIRMED,
        )
        assert second.pk != first.pk

    def test_cancelling_twice_is_rejected(self, provisioned_bot, service, staff, contact):
        appointment = services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(days=1),
        )
        services.cancel_appointment(appointment=appointment, actor=None)
        with pytest.raises(ConflictError):
            services.cancel_appointment(appointment=appointment, actor=None)


class TestBookingConversation:
    """The full customer-facing flow, through the real dispatcher."""

    @pytest.fixture
    def appointment_bot(self, catalogue, tenant_a, user, pool_entry, fake_transport):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram"], feature_slugs=["appointment"],
            currency="USD", business_draft={"name": "Tehran Smile Clinic"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

        job = run_job(create_job(order=order, strategy="pool"))
        assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"
        bot = job.bot
        _open_all_day(bot, dj_timezone.now().weekday())
        _open_all_day(bot, (dj_timezone.now().weekday() + 1) % 7)
        return bot

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

    def _tap(self, instance, update_id, payload):
        return self._dispatch(instance, {
            "update_id": update_id,
            "callback_query": {
                "id": "cb", "data": payload,
                "from": {"id": 777, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        })

    def test_a_single_staff_bot_goes_straight_from_service_to_slots(self, appointment_bot, fake_transport):
        """No staff-selection tap when there is only one staff member to pick."""
        instance = appointment_bot.instances.get(platform="telegram")
        services.create_service(bot=appointment_bot, actor=None, name="Cleaning", duration_minutes=30)
        services.get_or_create_default_staff(appointment_bot)

        self._dispatch(instance, self._message(1, "/book"))
        pick_service = self._callback_from(self._last_sent(instance), "Cleaning")

        result = self._tap(instance, 2, pick_service)
        # `pick_staff` is still what was invoked (the button was minted by `start_booking`
        # pointing straight at it) — it just auto-skipped internally to the slot list, so
        # the *reply* is the slot prompt, not a staff-selection prompt.
        assert result.route == "appointment:pick_staff"
        assert result.reply_text == "Available times:"
        buttons = self._last_sent(instance).payload["reply_markup"]["inline_keyboard"]
        assert any(row for row in buttons)

    def test_the_full_flow_books_a_real_appointment(self, appointment_bot, fake_transport):
        instance = appointment_bot.instances.get(platform="telegram")
        service = services.create_service(bot=appointment_bot, actor=None, name="Cleaning", duration_minutes=30)
        services.get_or_create_default_staff(appointment_bot)

        self._dispatch(instance, self._message(10, "/book"))
        pick_service = self._callback_from(self._last_sent(instance), "Cleaning")
        self._tap(instance, 11, pick_service)

        # Single staff member: this response is the slot list directly.
        slot_message = self._last_sent(instance)
        first_slot_label = slot_message.payload["reply_markup"]["inline_keyboard"][0][0]["text"]
        pick_slot = self._callback_from(slot_message, first_slot_label)
        result = self._tap(instance, 12, pick_slot)

        assert Appointment.objects.filter(bot=appointment_bot, service=service).count() == 1
        appointment = Appointment.objects.get(bot=appointment_bot, service=service)
        assert appointment.status == AppointmentStatus.CONFIRMED
        assert "Cleaning" in result.reply_text

    def test_multiple_staff_members_are_offered_a_choice(self, appointment_bot, fake_transport):
        instance = appointment_bot.instances.get(platform="telegram")
        service = services.create_service(bot=appointment_bot, actor=None, name="Cleaning", duration_minutes=30)
        services.create_staff(bot=appointment_bot, actor=None, name="Dr. Ada")
        services.create_staff(bot=appointment_bot, actor=None, name="Dr. Bijan")

        self._dispatch(instance, self._message(20, "/book"))
        pick_service = self._callback_from(self._last_sent(instance), "Cleaning")
        result = self._tap(instance, 21, pick_service)

        assert result.reply_text != "Available times:"
        buttons = self._last_sent(instance).payload["reply_markup"]["inline_keyboard"]
        labels = {b["text"] for row in buttons for b in row}
        assert labels == {"Dr. Ada", "Dr. Bijan"}

    def test_an_expired_selection_is_handled_gracefully(self, appointment_bot, fake_transport):
        """A service deleted between listing and tapping must not blow up the handler."""
        instance = appointment_bot.instances.get(platform="telegram")
        service = services.create_service(bot=appointment_bot, actor=None, name="Cleaning", duration_minutes=30)

        self._dispatch(instance, self._message(30, "/book"))
        pick_service = self._callback_from(self._last_sent(instance), "Cleaning")

        services.delete_service(bot=appointment_bot, service_id=service.pk, actor=None)

        result = self._tap(instance, 31, pick_service)
        assert result.handled
        assert result.reply_text == "That option is no longer available. Let's start over."


class TestOtherTemplatesShareTheSameBookingCode:
    """Booking is feature-driven, not template-driven — this is the whole reason
    'beauty' and 'services' (spec's next two Phase 7 templates, per PHASES.md) needed
    no new backend code at all: both templates simply offer the `appointment` feature
    the clinic template already exercises, and the same models/services/handlers serve
    all three. This locks that in rather than asserting it once and hoping it stays true.
    """

    @pytest.mark.parametrize("template_slug", ["beauty", "services"])
    def test_booking_works_end_to_end_on_a_non_clinic_template(
        self, template_slug, catalogue, tenant_a, user, pool_entry, fake_transport
    ):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug=template_slug, platforms=["telegram"], feature_slugs=["appointment"],
            currency="USD", business_draft={"name": f"{template_slug.title()} Biz"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

        job = run_job(create_job(order=order, strategy="pool"))
        assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"
        bot = job.bot
        _open_all_day(bot, dj_timezone.now().weekday())
        _open_all_day(bot, (dj_timezone.now().weekday() + 1) % 7)

        service = services.create_service(bot=bot, actor=None, name="Haircut", duration_minutes=30)
        services.get_or_create_default_staff(bot)

        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate, OutboundMessage

        instance = bot.instances.get(platform="telegram")

        def dispatch(update_id, payload):
            update = InboundUpdate.objects.create(instance=instance, platform_update_id=update_id, raw=payload)
            return dispatch_update(update)

        dispatch(1, {
            "update_id": 1,
            "message": {
                "message_id": 1, "text": "/book", "chat": {"id": 1},
                "from": {"id": 777, "first_name": "Ada", "username": "ada", "language_code": "en"},
            },
        })
        sent = OutboundMessage.objects.filter(instance=instance).latest("created_at")
        buttons = sent.payload["reply_markup"]["inline_keyboard"]
        pick_service = next(b["callback_data"] for row in buttons for b in row if b["text"] == "Haircut")

        result = dispatch(2, {
            "update_id": 2,
            "callback_query": {
                "id": "cb", "data": pick_service,
                "from": {"id": 777, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        })

        # Single default staff member auto-skips straight to the slot list — the exact
        # mechanics already proven for "clinic" in `TestBookingConversation`. Reaching
        # that same prompt on a different template's bot is the whole point here.
        assert result.handled
        assert result.route == "appointment:pick_staff"
        assert sent.payload["reply_markup"] is not None  # the service-selection prompt had choices
        assert result.reply_text  # a real slot-list (or no-availability) reply, not silence


class TestAppointmentApi:
    def test_service_crud_via_the_dashboard(self, auth_client, provisioned_bot):
        create = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointment-services/",
            {"name": "Cleaning", "duration_minutes": 30},
            format="json",
        )
        assert create.status_code == 201
        service_id = create.json()["id"]

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/appointment-services/")
        assert listed.status_code == 200
        assert any(s["id"] == service_id for s in listed.json())

        updated = auth_client.patch(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointment-services/{service_id}/",
            {"name": "Deep clean"}, format="json",
        )
        assert updated.status_code == 200 and updated.json()["name"] == "Deep clean"

        deleted = auth_client.delete(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointment-services/{service_id}/"
        )
        assert deleted.status_code == 204

    def test_staff_crud_via_the_dashboard(self, auth_client, provisioned_bot):
        create = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/staff/", {"name": "Dr. Ada"}, format="json"
        )
        assert create.status_code == 201
        assert create.json()["name"] == "Dr. Ada"

    def test_slots_endpoint(self, auth_client, provisioned_bot, service, staff):
        day = _next_weekday(0)
        WorkingHours.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, weekday=0,
            opens_at=time(9, 0), closes_at=time(12, 0),
        )
        response = auth_client.get(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointment-slots/",
            {"service": service.pk, "staff": staff.pk, "date": day.isoformat()},
        )
        assert response.status_code == 200
        assert len(response.json()) > 0

    def test_list_and_cancel_appointment(self, auth_client, provisioned_bot, service, staff, contact):
        appointment = services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(days=1),
        )

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/appointments/")
        assert listed.status_code == 200
        assert any(a["id"] == str(appointment.public_id) for a in listed.json())

        cancelled = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointments/{appointment.public_id}/cancel/",
            {"reason": "customer request"}, format="json",
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"

    def test_a_stranger_cannot_manage_another_tenants_services(self, other_client, provisioned_bot):
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/appointment-services/")
        assert response.status_code == 404

    def test_reschedule_moves_the_appointment_and_keeps_its_id(
        self, auth_client, provisioned_bot, service, staff, contact
    ):
        appointment = services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(days=1),
        )
        new_time = dj_timezone.now() + timedelta(days=2)

        response = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointments/{appointment.public_id}/reschedule/",
            {"starts_at": new_time.isoformat()}, format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(appointment.public_id)
        assert body["status"] == "CONFIRMED"

        appointment.refresh_from_db()
        assert appointment.starts_at == new_time

    def test_a_cancelled_appointment_cannot_be_rescheduled(
        self, auth_client, provisioned_bot, service, staff, contact
    ):
        appointment = services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(days=1),
        )
        services.cancel_appointment(appointment=appointment, actor=None)

        response = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointments/{appointment.public_id}/reschedule/",
            {"starts_at": (dj_timezone.now() + timedelta(days=2)).isoformat()}, format="json",
        )
        assert response.status_code == 409

    def test_rescheduling_into_the_past_is_rejected(
        self, auth_client, provisioned_bot, service, staff, contact
    ):
        appointment = services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(days=1),
        )
        response = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/appointments/{appointment.public_id}/reschedule/",
            {"starts_at": (dj_timezone.now() - timedelta(days=1)).isoformat()}, format="json",
        )
        assert response.status_code == 409


class TestReminders:
    @pytest.fixture
    def reminder_bot(self, catalogue, tenant_a, user, pool_entry, fake_transport):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug="clinic", platforms=["telegram"],
            feature_slugs=["appointment", "appointment_reminders"],
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

    def test_a_due_appointment_gets_reminded_exactly_once(self, reminder_bot, fake_transport):
        from apps.appointments.tasks import send_due_reminders
        from apps.bot_runtime.models import BusinessContact

        service = services.create_service(bot=reminder_bot, actor=None, name="Cleaning", duration_minutes=30)
        staff = services.create_staff(bot=reminder_bot, actor=None, name="Dr. Ada")
        contact = BusinessContact.objects.create(
            tenant=reminder_bot.tenant, bot=reminder_bot, platform="telegram", platform_user_id="777"
        )
        appointment = services.book_appointment(
            bot=reminder_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(minutes=45),
        )

        sent = send_due_reminders()

        assert sent == 1
        appointment.refresh_from_db()
        assert appointment.reminder_sent_at is not None
        assert fake_transport.called("sendMessage")

        # Idempotent: a re-run (Celery redelivery) must not send a second reminder.
        assert send_due_reminders() == 0
        assert sum(1 for name, _ in fake_transport.calls if name == "sendMessage") == 1

    def test_an_appointment_outside_the_lead_window_is_not_reminded(self, reminder_bot, fake_transport):
        from apps.appointments.tasks import send_due_reminders
        from apps.bot_runtime.models import BusinessContact

        service = services.create_service(bot=reminder_bot, actor=None, name="Cleaning", duration_minutes=30)
        staff = services.create_staff(bot=reminder_bot, actor=None, name="Dr. Ada")
        contact = BusinessContact.objects.create(
            tenant=reminder_bot.tenant, bot=reminder_bot, platform="telegram", platform_user_id="777"
        )
        services.book_appointment(
            bot=reminder_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(days=2),
        )

        assert send_due_reminders() == 0

    def test_a_bot_without_the_feature_is_not_reminded(self, provisioned_bot, service, staff, contact, fake_transport):
        """`provisioned_bot` never bought `appointment_reminders` — only `faq` and `contact`."""
        from apps.appointments.tasks import send_due_reminders

        services.book_appointment(
            bot=provisioned_bot, contact=contact, service=service, staff=staff,
            starts_at=dj_timezone.now() + timedelta(minutes=45),
        )

        assert send_due_reminders() == 0
