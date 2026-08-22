"""CRM: leads captured from a bot conversation (DATABASE.md §9).

Feedback lives here too rather than in its own app — one small table, owned by the same
`crm_pipeline`/`feedback` feature pair, not worth a fifth app for.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TenantOwnedModel
from apps.core.money import MoneyProxy


class LeadSource(models.TextChoices):
    CONTACT_FORM = "CONTACT_FORM", _("Contact form")
    CONSULTATION_REQUEST = "CONSULTATION_REQUEST", _("Consultation request")
    MANUAL = "MANUAL", _("Added manually")


class LeadStatus(models.TextChoices):
    NEW = "NEW", _("New")
    CONTACTED = "CONTACTED", _("Contacted")
    QUALIFIED = "QUALIFIED", _("Qualified")
    WON = "WON", _("Won")
    LOST = "LOST", _("Lost")


class Lead(PublicIdModel, TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="leads")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact", on_delete=models.CASCADE, related_name="leads"
    )

    source = models.CharField(max_length=24, choices=LeadSource.choices)
    status = models.CharField(max_length=16, choices=LeadStatus.choices, default=LeadStatus.NEW)

    message = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    #: An optional estimated deal value — set from the dashboard, never by the bot.
    value_minor = models.BigIntegerField(default=0)
    currency = CurrencyCodeField(blank=True)
    value = MoneyProxy("value_minor", "currency")

    assigned_to = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "crm_lead"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["bot", "status", "-created_at"], name="crm_lead_bot_status_idx")]

    def __str__(self) -> str:
        return f"Lead #{self.pk} ({self.source})"


class ContactNote(TenantOwnedModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()

    class Meta:
        db_table = "crm_contact_note"
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"note on lead #{self.lead_id}"


class Tag(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="crm_tags")
    name = models.CharField(max_length=64)
    leads = models.ManyToManyField(Lead, blank=True, related_name="tags")

    class Meta:
        db_table = "crm_tag"
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=["bot", "name"], name="crm_tag_bot_name_uniq")]

    def __str__(self) -> str:
        return self.name


class Feedback(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="feedback_entries")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact", on_delete=models.CASCADE, related_name="feedback_entries"
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)

    class Meta:
        db_table = "crm_feedback"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["bot", "-created_at"], name="crm_feedback_bot_time_idx")]

    def __str__(self) -> str:
        return f"{self.rating}★ from contact #{self.contact_id}"
