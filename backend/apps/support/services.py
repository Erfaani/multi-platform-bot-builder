"""Support ticket use cases.

The customer-facing surface is deliberately small: open a ticket, reply, close it.
Triage, assignment and internal notes are a staff job and live in Django admin — this
app does not need a second helpdesk UI to satisfy "runs the bot without contacting
support" (the exit criterion is that support is a fallback, not the main path).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.core.errors import ConflictError, NotFoundError, ValidationError
from apps.core.files import DOCUMENT_POLICY, validate_and_sanitise
from apps.support.models import (
    AuthorType,
    SupportAttachment,
    SupportMessage,
    SupportTicket,
    TicketStatus,
)


@transaction.atomic
def create_ticket(*, tenant, actor, subject: str, body: str, bot=None) -> SupportTicket:
    subject = subject.strip()
    body = body.strip()
    if not subject:
        raise ValidationError(
            code="support.subject_required", field_errors={"subject": ["A subject is required."]}
        )
    if not body:
        raise ValidationError(
            code="support.body_required", field_errors={"body": ["Describe the issue."]}
        )

    ticket = SupportTicket.objects.create(
        tenant=tenant,
        bot=bot,
        created_by=actor if getattr(actor, "pk", None) else None,
        subject=subject[:255],
        status=TicketStatus.OPEN,
        last_reply_at=timezone.now(),
    )
    SupportMessage.objects.create(
        ticket=ticket,
        author_type=AuthorType.CUSTOMER,
        author=actor if getattr(actor, "pk", None) else None,
        body=body,
    )
    record_audit(
        actor=actor,
        action="support.ticket_created",
        resource_type="support_ticket",
        resource_id=str(ticket.public_id),
        tenant=tenant,
        metadata={"subject": ticket.subject, "bot": str(bot.public_id) if bot else None},
    )
    return ticket


@transaction.atomic
def reply_to_ticket(*, ticket: SupportTicket, actor, body: str, upload=None) -> SupportMessage:
    """A customer reply. Reopens the ticket if it was waiting on them."""
    locked = SupportTicket.objects.select_for_update().get(pk=ticket.pk)

    if locked.status == TicketStatus.CLOSED:
        raise ConflictError(
            code="support.ticket_closed",
            message="This ticket is closed. Open a new one if the issue continues.",
        )

    body = body.strip()
    if not body:
        raise ValidationError(
            code="support.body_required", field_errors={"body": ["Write a message."]}
        )

    message = SupportMessage.objects.create(
        ticket=locked, author_type=AuthorType.CUSTOMER, author=actor, body=body
    )

    if upload is not None:
        safe = validate_and_sanitise(upload, DOCUMENT_POLICY)
        attachment = SupportAttachment(
            message=message,
            original_filename=safe.original_filename,
            content_type=safe.content_type,
            size_bytes=safe.size_bytes,
            sha256=safe.sha256,
        )
        attachment.file.save(safe.filename, safe.content, save=False)
        attachment.save()

    if locked.status == TicketStatus.WAITING_FOR_CUSTOMER:
        locked.status = TicketStatus.OPEN
    locked.last_reply_at = timezone.now()
    locked.save(update_fields=["status", "last_reply_at", "updated_at"])

    record_audit(
        actor=actor,
        action="support.ticket_replied",
        resource_type="support_ticket",
        resource_id=str(locked.public_id),
        tenant=locked.tenant,
        metadata={"has_attachment": upload is not None},
    )
    return message


@transaction.atomic
def close_ticket(*, ticket: SupportTicket, actor) -> SupportTicket:
    locked = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    if locked.status == TicketStatus.CLOSED:
        return locked  # idempotent

    locked.status = TicketStatus.CLOSED
    locked.save(update_fields=["status", "updated_at"])

    record_audit(
        actor=actor,
        action="support.ticket_closed",
        resource_type="support_ticket",
        resource_id=str(locked.public_id),
        tenant=locked.tenant,
        metadata={},
    )
    return locked


def get_ticket_for_tenant(*, public_id: str, tenant) -> SupportTicket:
    ticket = SupportTicket.objects.filter(public_id=public_id, tenant=tenant).first()
    if ticket is None:
        raise NotFoundError()
    return ticket


def list_messages(ticket: SupportTicket):
    """Customer-visible thread: internal notes are never returned here."""
    return ticket.messages.filter(is_internal_note=False).select_related("author").prefetch_related(
        "attachments"
    )
