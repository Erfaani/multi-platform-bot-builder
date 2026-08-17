"""Owner → customers broadcast (the `customer_broadcast` feature).

Fire-and-forget over Celery: a broadcast to hundreds of contacts must not block the
request, and the outbound gateway's existing per-bot/per-chat rate limits already handle
pacing — this just enqueues one send per contact and lets that machinery do its job.
"""

from __future__ import annotations

from celery import shared_task

from apps.audit.services import record_audit
from apps.core.errors import PermissionDeniedError, ValidationError


def send_broadcast(*, bot, actor, text: str) -> int:
    text = text.strip()
    if not text:
        raise ValidationError(code="broadcast.empty", field_errors={"text": ["Write a message."]})
    if len(text) > 2000:
        raise ValidationError(code="broadcast.too_long", field_errors={"text": ["Keep it under 2000 characters."]})
    if not bot.has_feature("customer_broadcast"):
        raise PermissionDeniedError(code="broadcast.feature_not_enabled")

    from apps.bot_runtime.models import BusinessContact

    contact_ids = list(
        BusinessContact.objects.filter(bot=bot, is_blocked=False).values_list("pk", flat=True)
    )
    if contact_ids:
        _dispatch_broadcast.delay(bot.pk, contact_ids, text)

    record_audit(
        actor=actor,
        action="broadcast.sent",
        resource_type="bot",
        resource_id=str(bot.public_id),
        tenant=bot.tenant,
        metadata={"recipients": len(contact_ids)},
    )
    return len(contact_ids)


@shared_task(ignore_result=True)
def _dispatch_broadcast(bot_id: int, contact_ids: list[int], text: str) -> None:
    from apps.bot_runtime.gateway import deliver
    from apps.bot_runtime.models import BusinessContact
    from apps.bots.models import BotPlatformInstance
    from apps.platforms.base import RenderContext, Reply
    from apps.platforms.preview.messages import translate
    from apps.platforms.registry import capabilities_for
    from apps.platforms.rendering import render_with_capabilities

    instances = {
        instance.platform: instance
        for instance in BotPlatformInstance.objects.filter(
            bot_id=bot_id, status=BotPlatformInstance.Status.ACTIVE
        )
    }
    if not instances:
        return

    reply = Reply(text_key=f"literal:{text}")
    for contact in BusinessContact.objects.filter(pk__in=contact_ids):
        instance = instances.get(contact.platform)
        if instance is None:
            continue
        render_ctx = RenderContext(
            locale=contact.locale or "en", business_name="", translate=translate
        )
        message = render_with_capabilities(reply, render_ctx, capabilities_for(contact.platform))
        deliver(instance=instance, chat_ref=contact.platform_user_id, message=message, is_bulk=True)
