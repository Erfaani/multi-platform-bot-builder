"""CRM use cases: leads captured from a bot conversation, and feedback."""

from __future__ import annotations

from django.db import transaction

from apps.audit.services import record_audit
from apps.core.errors import NotFoundError, ValidationError
from apps.core.events import publish

from apps.crm.models import ContactNote, Feedback, Lead, LeadStatus, Tag


@transaction.atomic
def create_lead(*, bot, contact, source: str, message: str = "", phone: str = "", email: str = "") -> Lead:
    lead = Lead.objects.create(
        tenant=bot.tenant,
        bot=bot,
        contact=contact,
        source=source,
        message=message[:4000],
        phone=phone[:32],
        email=email[:254],
    )
    record_audit(
        actor=None,
        action="crm.lead_captured",
        resource_type="lead",
        resource_id=str(lead.public_id),
        tenant=bot.tenant,
        metadata={"source": source},
    )
    publish(
        "crm.lead_captured",
        {
            "tenant_id": str(bot.tenant.public_id),
            "bot_id": str(bot.public_id),
            "dedupe_key": f"lead:{lead.public_id}",
            # A plain string, not `.label` — that's a lazy translation proxy and not
            # JSON-serializable, and event payloads must stay locale-agnostic besides;
            # `notify.lead.captured.body` is where this gets a translated presentation.
            "source": str(source),
        },
    )
    return lead


def list_leads(bot) -> list[Lead]:
    return list(
        Lead.objects.filter(bot=bot)
        .select_related("contact", "assigned_to")
        .prefetch_related("notes", "tags")
        .order_by("-created_at")
    )


def get_lead_for_bot(*, bot, lead_id) -> Lead:
    lead = Lead.objects.filter(bot=bot, public_id=lead_id).select_related("contact").first()
    if lead is None:
        raise NotFoundError()
    return lead


@transaction.atomic
def update_lead(*, bot, lead_id, actor, **fields) -> Lead:
    lead = get_lead_for_bot(bot=bot, lead_id=lead_id)

    changed: list[str] = []
    for key in ("status", "value_minor", "currency", "assigned_to_id"):
        if key in fields and fields[key] is not None:
            if key == "status" and fields[key] not in LeadStatus.values:
                raise ValidationError(
                    code="crm.invalid_status", field_errors={"status": ["Not a valid status."]}
                )
            setattr(lead, key, fields[key])
            changed.append(key)

    if changed:
        lead.save(update_fields=[*changed, "updated_at"])
        record_audit(
            actor=actor,
            action="crm.lead_updated",
            resource_type="lead",
            resource_id=str(lead.public_id),
            tenant=bot.tenant,
            metadata={"fields": changed},
        )
    return lead


@transaction.atomic
def add_note(*, bot, lead_id, actor, body: str) -> ContactNote:
    body = body.strip()
    if not body:
        raise ValidationError(code="crm.note_required", field_errors={"body": ["Write a note."]})

    lead = get_lead_for_bot(bot=bot, lead_id=lead_id)
    note = ContactNote.objects.create(tenant=bot.tenant, lead=lead, author=actor, body=body)
    record_audit(
        actor=actor,
        action="crm.note_added",
        resource_type="lead",
        resource_id=str(lead.public_id),
        tenant=bot.tenant,
    )
    return note


def list_tags(bot) -> list[Tag]:
    return list(Tag.objects.filter(bot=bot).order_by("name"))


@transaction.atomic
def tag_lead(*, bot, lead_id, actor, tag_name: str) -> Tag:
    tag_name = tag_name.strip()[:64]
    if not tag_name:
        raise ValidationError(code="crm.tag_required", field_errors={"tag": ["Required."]})

    lead = get_lead_for_bot(bot=bot, lead_id=lead_id)
    tag, _ = Tag.objects.get_or_create(tenant=bot.tenant, bot=bot, name=tag_name)
    tag.leads.add(lead)
    return tag


# --------------------------------------------------------------------------- feedback


@transaction.atomic
def record_feedback(*, bot, contact, rating: int, comment: str = "") -> Feedback:
    if not 1 <= rating <= 5:
        raise ValidationError(code="crm.invalid_rating", field_errors={"rating": ["1 to 5."]})

    feedback = Feedback.objects.create(
        tenant=bot.tenant, bot=bot, contact=contact, rating=rating, comment=comment[:2000]
    )
    record_audit(
        actor=None,
        action="crm.feedback_recorded",
        resource_type="feedback",
        resource_id=str(feedback.pk),
        tenant=bot.tenant,
        metadata={"rating": rating},
    )
    return feedback


def list_feedback(bot) -> list[Feedback]:
    return list(Feedback.objects.filter(bot=bot).select_related("contact").order_by("-created_at"))
