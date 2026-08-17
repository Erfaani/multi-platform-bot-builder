"""Webhook ingress (BOT_RUNTIME.md §2).

This view does the least work of anything on the platform, on purpose: authenticate,
persist, enqueue, return 200. No business logic, no outbound calls. If it is slow the
platform retries, and retries multiply load exactly when the system is already struggling.

It returns **200 for everything**, including rejected requests. A 404 would tell an
attacker which bot ids exist, and a 500 would make Telegram retry a message we have
already decided to drop.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.bots.models import WebhookSecret
from apps.bot_runtime.context import load_instance
from apps.bot_runtime.models import InboundUpdate

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024 * 1024  # Telegram updates are far smaller; this is a sanity cap.
MAX_JSON_DEPTH = 32

TELEGRAM_SECRET_HEADER = "HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN"
GENERIC_SIGNATURE_HEADER = "HTTP_X_WEBHOOK_SIGNATURE"

OK = JsonResponse({"ok": True})


def _ok() -> HttpResponse:
    return JsonResponse({"ok": True})


def _json_depth(value, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max((_json_depth(v, depth + 1) for v in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(v, depth + 1) for v in value), default=depth)
    return depth


def _active_secret_hashes(instance) -> list[str]:
    """Hashes of every currently valid secret.

    More than one may be valid during rotation, so an update already in flight under the
    old secret is not dropped.
    """
    now = timezone.now()
    return list(
        WebhookSecret.objects.filter(instance=instance, is_active=True)
        .filter(valid_from__lte=now)
        .exclude(valid_to__lt=now)
        .values_list("secret_hash", flat=True)
    )


def _authenticate(request: HttpRequest, instance, raw_body: bytes) -> bool:
    """Verify the caller knows this bot's secret, in constant time."""
    valid_hashes = _active_secret_hashes(instance)
    if not valid_hashes:
        return False

    presented = request.META.get(TELEGRAM_SECRET_HEADER, "")
    if presented:
        digest = hashlib.sha256(presented.encode()).hexdigest()
        return any(hmac.compare_digest(digest, known) for known in valid_hashes)

    # Platforms without a secret-token header sign the body instead.
    signature = request.META.get(GENERIC_SIGNATURE_HEADER, "")
    if signature:
        for known in valid_hashes:
            expected = hmac.new(known.encode(), raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(signature, expected):
                return True

    return False


@csrf_exempt
@require_POST
def webhook(request: HttpRequest, platform: str, instance_public_id: str) -> HttpResponse:
    if len(request.body) > MAX_BODY_BYTES:
        logger.warning("Oversized webhook body for %s", instance_public_id)
        return _ok()

    instance = load_instance(platform, instance_public_id)
    if instance is None:
        # Unknown, suspended, or wrong platform. Suspension stopping the bot is the
        # point: otherwise an unpaid subscription keeps working.
        return _ok()

    if not _authenticate(request, instance, request.body):
        logger.warning("Rejected an unauthenticated webhook for %s", instance_public_id)
        return _ok()

    try:
        payload = json.loads(request.body)
    except ValueError:
        return _ok()

    if not isinstance(payload, dict) or _json_depth(payload) > MAX_JSON_DEPTH:
        return _ok()

    update_id = payload.get("update_id")
    if update_id is None:
        return _ok()

    try:
        # Wrapped in its own atomic block: an IntegrityError leaves a transaction
        # unusable, and on redelivery — which is routine, not exceptional — we still
        # need to answer 200.
        with transaction.atomic():
            update = InboundUpdate.objects.create(
                instance=instance, platform_update_id=int(update_id), raw=payload
            )
    except IntegrityError:
        # We already have this update. Acknowledge and do nothing.
        return _ok()
    except (TypeError, ValueError):
        return _ok()

    _enqueue(update.pk, platform)
    return _ok()


def _enqueue(update_pk: int, platform: str) -> None:
    from apps.bot_runtime.tasks import process_update

    try:
        process_update.apply_async(args=[update_pk], queue=platform)
    except Exception:
        # The update is already durable; the sweeper will pick it up. Never fail the
        # webhook over a broker hiccup — the platform would just retry and pile on.
        logger.warning(
            "Could not enqueue update %s; the sweeper will retry it.", update_pk, exc_info=True
        )
