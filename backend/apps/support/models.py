"""Support tickets (DATABASE.md §10).

The exit criterion for Phase 6 is that a customer runs their bot without contacting
support — but when they do need to, this is where that conversation lives, instead of
in an inbox no one else on the team can see.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PublicIdModel, TenantOwnedModel, TimeStampedModel


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", _("Open")
    IN_PROGRESS = "IN_PROGRESS", _("In progress")
    WAITING_FOR_CUSTOMER = "WAITING_FOR_CUSTOMER", _("Waiting for customer")
    RESOLVED = "RESOLVED", _("Resolved")
    CLOSED = "CLOSED", _("Closed")


#: Statuses the customer can still act on (reply, close). A ticket that has been
#: reopened does not exist in this model — closing is final; a new problem is a new
#: ticket, which keeps the history honest.
OPEN_STATUSES = frozenset(
    {TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_CUSTOMER, TicketStatus.RESOLVED}
)


class TicketPriority(models.TextChoices):
    LOW = "LOW", _("Low")
    NORMAL = "NORMAL", _("Normal")
    HIGH = "HIGH", _("High")
    URGENT = "URGENT", _("Urgent")


class SupportTicket(PublicIdModel, TenantOwnedModel):
    """One support conversation. May or may not be about a specific bot."""

    bot = models.ForeignKey(
        "bots.Bot", null=True, blank=True, on_delete=models.SET_NULL, related_name="support_tickets"
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assigned_to = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    subject = models.CharField(max_length=255)
    status = models.CharField(
        max_length=24, choices=TicketStatus.choices, default=TicketStatus.OPEN, db_index=True
    )
    priority = models.CharField(
        max_length=16, choices=TicketPriority.choices, default=TicketPriority.NORMAL
    )
    last_reply_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "support_ticket"
        ordering = ("-last_reply_at", "-created_at")
        indexes = [
            models.Index(fields=["tenant", "status", "-last_reply_at"], name="support_ticket_status_idx"),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.subject}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


class AuthorType(models.TextChoices):
    CUSTOMER = "CUSTOMER", _("Customer")
    STAFF = "STAFF", _("Staff")


class SupportMessage(TimeStampedModel):
    """One message in a ticket's thread."""

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author_type = models.CharField(max_length=16, choices=AuthorType.choices)
    author = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()

    #: Staff-only remarks in the same thread, e.g. "waiting on billing to confirm".
    #: Never serialised to a customer-facing response.
    is_internal_note = models.BooleanField(default=False)

    class Meta:
        db_table = "support_message"
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"message on ticket #{self.ticket_id}"


class SupportAttachment(TimeStampedModel):
    """A file attached to one message. Validated per SECURITY.md §7."""

    message = models.ForeignKey(SupportMessage, on_delete=models.CASCADE, related_name="attachments")

    file = models.FileField(upload_to="support/%Y/%m/", max_length=255)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)

    class Meta:
        db_table = "support_attachment"

    def __str__(self) -> str:
        return self.original_filename
