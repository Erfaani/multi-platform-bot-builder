"""Owner admin menu — day-to-day bot management from inside the chat (Phase 10.5).

Per the product's hybrid model: simple, frequent tasks are handled here; anything
complex or structural defers to the website ("My Bots -> Bot Management"). Namespaced
under `core:` (not a feature slug) because this is a permission-gated builtin, not a
purchasable feature — every route here re-checks membership itself rather than trusting
the menu was only reachable by an owner, since a signed callback minted while linked
must stop working the moment the membership is removed.
"""

from __future__ import annotations

from apps.bot_runtime.handlers import HandlerResult, command, route, state
from apps.platforms.base import Choice, Reply

from apps.customers.services import resolve_tenant_membership


def _is_owner(ctx, event) -> bool:
    membership = resolve_tenant_membership(
        platform=ctx.platform, platform_user_id=event.user_ref, tenant_id=ctx.tenant_id
    )
    return membership is not None and membership.has_scope("bots.manage")


def _not_linked() -> HandlerResult:
    return HandlerResult(reply=Reply(text_key="bot.admin.not_linked"), next_state="IDLE")


def _menu_reply() -> Reply:
    return Reply(
        text_key="bot.admin.menu",
        choices=[
            Choice(label_key="bot.admin.recentLeads", value="core:admin_leads"),
            Choice(label_key="bot.admin.todaysAppointments", value="core:admin_appointments"),
            Choice(label_key="bot.admin.addFaq", value="core:admin_faq_start"),
            Choice(label_key="bot.admin.moreSettings", value="core:admin_more"),
        ],
    )


@command("admin")
@route("core:admin_menu")
def admin_menu(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not _is_owner(ctx, event):
        return _not_linked()
    session.reset()
    return HandlerResult(reply=_menu_reply(), next_state="IDLE")


@route("core:admin_leads")
def admin_leads(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not _is_owner(ctx, event):
        return _not_linked()

    from apps.bots.models import Bot
    from apps.crm import services as crm_services

    bot = Bot.objects.get(pk=ctx.bot_id)
    leads = crm_services.list_leads(bot)[:5]
    if not leads:
        return HandlerResult(reply=Reply(text_key="bot.admin.noLeads"), next_state="IDLE")

    lines = "\n".join(
        f"- {lead.contact.display_name or '—'} ({lead.get_status_display()})" for lead in leads
    )
    return HandlerResult(
        reply=Reply(text_key="bot.admin.leadsList", params={"lines": lines}), next_state="IDLE"
    )


@route("core:admin_appointments")
def admin_appointments(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not _is_owner(ctx, event):
        return _not_linked()

    from datetime import timedelta

    from django.utils import timezone as dj_timezone

    from apps.appointments import services as appointment_services
    from apps.bots.models import Bot

    bot = Bot.objects.get(pk=ctx.bot_id)
    horizon = dj_timezone.now() + timedelta(hours=24)
    upcoming = [
        a for a in appointment_services.list_appointments(bot) if a.starts_at <= horizon
    ][:5]
    if not upcoming:
        return HandlerResult(reply=Reply(text_key="bot.admin.noAppointments"), next_state="IDLE")

    lines = "\n".join(
        f"- {dj_timezone.localtime(a.starts_at).strftime('%H:%M')} {a.service.name} "
        f"({a.contact.display_name or '—'})"
        for a in upcoming
    )
    return HandlerResult(
        reply=Reply(text_key="bot.admin.appointmentsList", params={"lines": lines}),
        next_state="IDLE",
    )


@route("core:admin_faq_start")
def admin_faq_start(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not _is_owner(ctx, event):
        return _not_linked()

    return HandlerResult(
        reply=Reply(text_key="bot.admin.faqAskQuestion", expects="text"),
        next_state="admin:awaiting_faq_question",
    )


@state("admin:awaiting_faq_question")
def admin_faq_question(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        session.reset()
        return admin_menu(event, session, ctx, value, locale)
    if not _is_owner(ctx, event):
        session.reset()
        return _not_linked()

    text = (event.text or "").strip()
    if not text:
        return HandlerResult(
            reply=Reply(text_key="bot.admin.faqAskQuestion", expects="text"),
            next_state="admin:awaiting_faq_question",
        )

    session.set("admin_faq_question", text)
    return HandlerResult(
        reply=Reply(text_key="bot.admin.faqAskAnswer", expects="text"),
        next_state="admin:awaiting_faq_answer",
    )


@state("admin:awaiting_faq_answer")
def admin_faq_answer(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        session.reset()
        return admin_menu(event, session, ctx, value, locale)
    if not _is_owner(ctx, event):
        session.reset()
        return _not_linked()

    text = (event.text or "").strip()
    if not text:
        return HandlerResult(
            reply=Reply(text_key="bot.admin.faqAskAnswer", expects="text"),
            next_state="admin:awaiting_faq_answer",
        )

    from apps.bots.models import Bot
    from apps.businesses import services as business_services

    bot = Bot.objects.select_related("tenant").get(pk=ctx.bot_id)
    question = session.get("admin_faq_question", "")
    business_services.create_faq_entry(bot=bot, actor=None, question=question, answer=text)

    session.reset()
    return HandlerResult(reply=Reply(text_key="bot.admin.faqAdded"), next_state="IDLE")


@route("core:admin_more")
def admin_more(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not _is_owner(ctx, event):
        return _not_linked()
    return HandlerResult(reply=Reply(text_key="bot.admin.moreSettingsInfo"), next_state="IDLE")
