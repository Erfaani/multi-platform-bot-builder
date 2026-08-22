"""Business profile and FAQ use cases.

This is what makes spec §24 real: a customer edits their own business details and FAQ
from the dashboard, and the bot reflects it on the next message — no support ticket, no
redeploy. Every write bumps `BotConfiguration.version`, which is the runtime's cache key
(`bot_runtime/context.py`), so the change is live immediately rather than after a TTL.
"""

from __future__ import annotations

from django.db import transaction

from apps.audit.services import record_audit
from apps.bots.models import Bot
from apps.businesses.models import BusinessProfile, FaqEntry, WorkingHours
from apps.core.errors import NotFoundError, ValidationError

#: What a customer may edit themselves via the plain profile fields. Logo and
#: structured per-weekday hours have their own dedicated functions below, since both
#: need more than a plain `setattr` (a file to validate/store, or a whole-week replace).
#: `working_hours_text` stays here — it is still what the `business:hours` handler
#: renders verbatim; `WorkingHours` rows are read only by appointment slot computation.
EDITABLE_PROFILE_FIELDS = (
    "display_name",
    "description",
    "phone",
    "secondary_phone",
    "email",
    "website",
    "address",
    "city",
    "working_hours_text",
)


def get_or_create_profile(bot: Bot) -> BusinessProfile:
    profile, created = BusinessProfile.objects.get_or_create(
        bot=bot,
        defaults={"tenant": bot.tenant, "display_name": bot.name},
    )
    return profile


@transaction.atomic
def update_business_profile(*, bot: Bot, actor, **fields) -> BusinessProfile:
    profile = get_or_create_profile(bot)

    changed: list[str] = []
    for key, value in fields.items():
        if key not in EDITABLE_PROFILE_FIELDS or value is None:
            continue
        setattr(profile, key, value)
        changed.append(key)

    if changed:
        profile.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor,
            action="business_profile.updated",
            resource_type="business_profile",
            resource_id=str(profile.pk),
            tenant=bot.tenant,
            metadata={"fields": changed},
        )
    return profile


@transaction.atomic
def set_business_logo(*, bot: Bot, actor, upload) -> BusinessProfile:
    from apps.core.files import PUBLIC_IMAGE_POLICY, validate_and_sanitise

    profile = get_or_create_profile(bot)
    safe = validate_and_sanitise(upload, PUBLIC_IMAGE_POLICY)
    if profile.logo:
        profile.logo.delete(save=False)
    profile.logo.save(safe.filename, safe.content, save=False)
    profile.save(update_fields=["logo", "updated_at"])
    bot.configuration.bump()
    record_audit(
        actor=actor,
        action="business_profile.logo_updated",
        resource_type="business_profile",
        resource_id=str(profile.pk),
        tenant=bot.tenant,
    )
    return profile


def list_working_hours(bot_id: int) -> list[WorkingHours]:
    return list(WorkingHours.objects.filter(bot_id=bot_id).order_by("weekday", "opens_at"))


@transaction.atomic
def set_working_hours(*, bot: Bot, actor, days: list[dict]) -> list[WorkingHours]:
    """Replace the whole week in one call.

    Simpler for the client than per-row CRUD, and matches how the form is naturally
    edited — a customer sets all seven days at once, not one row at a time.
    """
    for day in days:
        if not day.get("is_closed") and (not day.get("opens_at") or not day.get("closes_at")):
            raise ValidationError(
                code="working_hours.incomplete",
                message="Give both an opening and closing time, or mark the day closed.",
            )
        if not day.get("is_closed") and day["opens_at"] >= day["closes_at"]:
            raise ValidationError(
                code="working_hours.invalid_range",
                message="Opening time must be before closing time.",
            )

    WorkingHours.objects.filter(bot=bot).delete()
    WorkingHours.objects.bulk_create(
        WorkingHours(
            tenant=bot.tenant,
            bot=bot,
            weekday=day["weekday"],
            opens_at=day.get("opens_at"),
            closes_at=day.get("closes_at"),
            is_closed=day.get("is_closed", False),
        )
        for day in days
    )
    bot.configuration.bump()
    record_audit(
        actor=actor,
        action="business_profile.working_hours_updated",
        resource_type="business_profile",
        resource_id=str(bot.pk),
        tenant=bot.tenant,
    )
    return list_working_hours(bot.pk)


def list_faq(bot: Bot) -> list[FaqEntry]:
    return list(FaqEntry.objects.filter(bot=bot).order_by("sort_order", "id"))


@transaction.atomic
def create_faq_entry(*, bot: Bot, actor, question: str, answer: str, sort_order: int = 100) -> FaqEntry:
    question = question.strip()
    answer = answer.strip()
    if not question or not answer:
        raise ValidationError(
            code="faq.incomplete",
            field_errors={
                "question": [] if question else ["A question is required."],
                "answer": [] if answer else ["An answer is required."],
            },
        )

    entry = FaqEntry.objects.create(
        tenant=bot.tenant,
        bot=bot,
        question=question[:255],
        answer=answer,
        sort_order=sort_order,
        source=FaqEntry.Source.MANUAL,
    )
    bot.configuration.bump()
    record_audit(
        actor=actor,
        action="faq.created",
        resource_type="faq_entry",
        resource_id=str(entry.pk),
        tenant=bot.tenant,
    )
    return entry


@transaction.atomic
def update_faq_entry(*, bot: Bot, entry_id: int, actor, **fields) -> FaqEntry:
    entry = FaqEntry.objects.filter(bot=bot, pk=entry_id).first()
    if entry is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in ("question", "answer", "sort_order", "is_active"):
        if key in fields and fields[key] is not None:
            setattr(entry, key, fields[key])
            changed.append(key)

    if changed:
        entry.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor,
            action="faq.updated",
            resource_type="faq_entry",
            resource_id=str(entry.pk),
            tenant=bot.tenant,
            metadata={"fields": changed},
        )
    return entry


@transaction.atomic
def delete_faq_entry(*, bot: Bot, entry_id: int, actor) -> None:
    entry = FaqEntry.objects.filter(bot=bot, pk=entry_id).first()
    if entry is None:
        raise NotFoundError()

    entry.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor,
        action="faq.deleted",
        resource_type="faq_entry",
        resource_id=str(entry_id),
        tenant=bot.tenant,
    )


def business_context_dict(bot: Bot) -> dict:
    """The dict `BotContext.business` resolves to (`bot_runtime/context.py`).

    Kept here, next to the model it reads, rather than in `bot_runtime` — the runtime
    stays generic and just asks "what does this app know about the bot's business".
    Falls back to nothing (empty dict) rather than raising: a bot mid-provisioning, or
    one seeded before this profile existed, must still render *something*.
    """
    profile = BusinessProfile.objects.filter(bot_id=bot.pk).first()
    if profile is None:
        return {}

    return {
        "name": profile.display_name or bot.name,
        "description": profile.description,
        "phone": profile.phone,
        "email": profile.email,
        "address": profile.address,
        "working_hours": profile.working_hours_text,
    }
