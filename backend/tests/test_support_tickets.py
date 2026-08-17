"""Support tickets — the fallback when a customer cannot self-serve (Phase 6)."""

from __future__ import annotations

import pytest

from apps.core.errors import ConflictError, ValidationError
from apps.support.models import AuthorType, SupportTicket, TicketStatus
from apps.support.services import close_ticket, create_ticket, reply_to_ticket

pytestmark = pytest.mark.django_db


class TestCreateTicket:
    def test_creates_a_ticket_with_the_first_message(self, tenant_a, user):
        ticket = create_ticket(
            tenant=tenant_a, actor=user, subject="Bot is not replying", body="Since this morning."
        )
        assert ticket.status == TicketStatus.OPEN
        assert ticket.messages.count() == 1
        assert ticket.messages.get().author_type == AuthorType.CUSTOMER
        assert ticket.last_reply_at is not None

    def test_can_be_scoped_to_a_specific_bot(self, provisioned_bot, user):
        ticket = create_ticket(
            tenant=provisioned_bot.tenant, actor=user, subject="Question", body="Hi", bot=provisioned_bot
        )
        assert ticket.bot_id == provisioned_bot.pk

    def test_an_empty_subject_is_rejected(self, tenant_a, user):
        with pytest.raises(ValidationError):
            create_ticket(tenant=tenant_a, actor=user, subject="  ", body="Hi")

    def test_an_empty_body_is_rejected(self, tenant_a, user):
        with pytest.raises(ValidationError):
            create_ticket(tenant=tenant_a, actor=user, subject="Hi", body="  ")


class TestReplyToTicket:
    def test_a_reply_is_appended_and_bumps_last_reply_at(self, tenant_a, user):
        ticket = create_ticket(tenant=tenant_a, actor=user, subject="S", body="B")
        first_reply_at = ticket.last_reply_at

        reply_to_ticket(ticket=ticket, actor=user, body="Following up.")

        ticket.refresh_from_db()
        assert ticket.messages.count() == 2
        assert ticket.last_reply_at >= first_reply_at

    def test_a_reply_reopens_a_ticket_waiting_on_the_customer(self, tenant_a, user):
        ticket = create_ticket(tenant=tenant_a, actor=user, subject="S", body="B")
        ticket.status = TicketStatus.WAITING_FOR_CUSTOMER
        ticket.save(update_fields=["status"])

        reply_to_ticket(ticket=ticket, actor=user, body="Here is the info you asked for.")

        ticket.refresh_from_db()
        assert ticket.status == TicketStatus.OPEN

    def test_cannot_reply_to_a_closed_ticket(self, tenant_a, user):
        ticket = create_ticket(tenant=tenant_a, actor=user, subject="S", body="B")
        close_ticket(ticket=ticket, actor=user)

        with pytest.raises(ConflictError):
            reply_to_ticket(ticket=ticket, actor=user, body="Still there?")

    def test_an_empty_reply_is_rejected(self, tenant_a, user):
        ticket = create_ticket(tenant=tenant_a, actor=user, subject="S", body="B")
        with pytest.raises(ValidationError):
            reply_to_ticket(ticket=ticket, actor=user, body="   ")

    def test_internal_notes_are_never_returned_to_the_customer(self, tenant_a, user):
        from apps.support.models import SupportMessage
        from apps.support.services import list_messages

        ticket = create_ticket(tenant=tenant_a, actor=user, subject="S", body="B")
        SupportMessage.objects.create(
            ticket=ticket,
            author_type=AuthorType.STAFF,
            body="internal: escalate to billing",
            is_internal_note=True,
        )

        bodies = [m.body for m in list_messages(ticket)]
        assert "internal: escalate to billing" not in bodies


class TestCloseTicket:
    def test_closing_is_idempotent(self, tenant_a, user):
        ticket = create_ticket(tenant=tenant_a, actor=user, subject="S", body="B")
        close_ticket(ticket=ticket, actor=user)
        closed_again = close_ticket(ticket=ticket, actor=user)
        assert closed_again.status == TicketStatus.CLOSED


class TestSupportTicketApi:
    def test_create_list_and_retrieve(self, auth_client, tenant_a):
        create = auth_client.post(
            "/api/v1/support/tickets/",
            {"subject": "Payment question", "body": "How do I change cards?"},
            format="json",
        )
        assert create.status_code == 201
        ticket_id = create.json()["id"]
        assert len(create.json()["messages"]) == 1

        listed = auth_client.get("/api/v1/support/tickets/")
        assert listed.status_code == 200
        assert any(t["id"] == ticket_id for t in listed.json())

        detail = auth_client.get(f"/api/v1/support/tickets/{ticket_id}/")
        assert detail.status_code == 200
        assert detail.json()["subject"] == "Payment question"

    def test_reply_then_close(self, auth_client, tenant_a):
        ticket_id = auth_client.post(
            "/api/v1/support/tickets/", {"subject": "S", "body": "B"}, format="json"
        ).json()["id"]

        reply = auth_client.post(
            f"/api/v1/support/tickets/{ticket_id}/reply/", {"body": "More detail."}, format="json"
        )
        assert reply.status_code == 201
        assert len(reply.json()["messages"]) == 2

        closed = auth_client.post(f"/api/v1/support/tickets/{ticket_id}/close/")
        assert closed.status_code == 200
        assert closed.json()["status"] == TicketStatus.CLOSED

    def test_a_stranger_cannot_see_another_tenants_ticket(self, auth_client, other_client, tenant_a):
        ticket_id = auth_client.post(
            "/api/v1/support/tickets/", {"subject": "S", "body": "B"}, format="json"
        ).json()["id"]

        response = other_client.get(f"/api/v1/support/tickets/{ticket_id}/")
        assert response.status_code == 404

    def test_unauthenticated_is_rejected(self, api):
        response = api.get("/api/v1/support/tickets/")
        assert response.status_code == 401

    def test_create_requires_subject_and_body(self, auth_client):
        response = auth_client.post(
            "/api/v1/support/tickets/", {"subject": "", "body": ""}, format="json"
        )
        assert response.status_code == 400
