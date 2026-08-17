"""Credential acquisition strategies (ADR-0002).

Telegram has no bot-creation API, so the unavoidable manual step has to live *somewhere*.
These three implementations put it in three different places; the order records which was
used, so support can always answer "how did this customer get their bot".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bots import credentials as credential_service
from apps.bots.models import AcquisitionMode, BotPlatformInstance, BotPoolEntry
from apps.core.errors import ConflictError

logger = logging.getLogger(__name__)

#: How long a pool entry stays reserved before it returns to stock. Long enough to
#: survive a slow provisioning run, short enough that a crash does not leak inventory.
RESERVATION_TTL = timedelta(minutes=15)


class AcquisitionOutcome:
    ACQUIRED = "ACQUIRED"
    #: Tier B: nothing is wrong, we simply need the customer now.
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    outcome: str
    detail: dict


class ProvisioningStrategy(Protocol):
    slug: str
    acquisition_mode: str

    def acquire(self, instance: BotPlatformInstance) -> AcquisitionResult: ...
    def release(self, instance: BotPlatformInstance) -> None: ...


class PoolAssignmentStrategy:
    """Tier A — Instant. Claim a pre-created bot and reconfigure it."""

    slug = "pool"
    acquisition_mode = AcquisitionMode.POOL

    @transaction.atomic
    def acquire(self, instance: BotPlatformInstance) -> AcquisitionResult:
        # If this job already claimed an entry, reuse it — the saga is resumable.
        existing = BotPoolEntry.objects.filter(assigned_instance=instance).first()
        if existing is not None:
            return AcquisitionResult(AcquisitionOutcome.ACQUIRED, {"username": existing.username})

        now = timezone.now()
        entry = (
            BotPoolEntry.objects.select_for_update(skip_locked=True)
            .filter(platform=instance.platform)
            .filter(
                models_q_available(now)
            )
            .order_by("created_at")
            .first()
        )
        if entry is None:
            raise ConflictError(
                code="provisioning.pool_empty",
                message=(
                    f"No {instance.platform} bots are available in the pool. "
                    "Operations must restock before this order can be provisioned."
                ),
            )

        entry.status = BotPoolEntry.Status.ASSIGNED
        entry.reserved_until = None
        entry.assigned_instance = instance
        entry.save(update_fields=["status", "reserved_until", "assigned_instance", "updated_at"])

        credential_service.transfer_pool_credential(entry=entry, instance=instance)

        instance.username = entry.username
        instance.platform_bot_id = entry.platform_bot_id
        instance.acquisition_mode = self.acquisition_mode
        instance.save(update_fields=["username", "platform_bot_id", "acquisition_mode", "updated_at"])

        return AcquisitionResult(AcquisitionOutcome.ACQUIRED, {"username": entry.username})

    @transaction.atomic
    def release(self, instance: BotPlatformInstance) -> None:
        """Compensation: return a claimed entry to stock so it is not leaked."""
        entry = BotPoolEntry.objects.select_for_update().filter(assigned_instance=instance).first()
        if entry is None:
            return
        entry.status = BotPoolEntry.Status.AVAILABLE
        entry.assigned_instance = None
        entry.reserved_until = None
        entry.save(update_fields=["status", "assigned_instance", "reserved_until", "updated_at"])
        logger.info("Returned pool entry @%s to stock", entry.username)


def models_q_available(now):
    """Available, or reserved so long ago the reservation has clearly been abandoned."""
    from django.db.models import Q

    return Q(status=BotPoolEntry.Status.AVAILABLE) | Q(
        status=BotPoolEntry.Status.RESERVED, reserved_until__lt=now
    )


class TokenHandoffStrategy:
    """Tier B — Custom username. The customer pastes their token once.

    Acquisition is not something we *do* here; it is something we *wait for*. The
    customer submits the token through the dashboard, which stores the credential and
    resumes the saga.
    """

    slug = "token_handoff"
    acquisition_mode = AcquisitionMode.TOKEN_HANDOFF

    def acquire(self, instance: BotPlatformInstance) -> AcquisitionResult:
        if hasattr(instance, "credential"):
            return AcquisitionResult(
                AcquisitionOutcome.ACQUIRED, {"username": instance.username}
            )

        if instance.status != BotPlatformInstance.Status.AWAITING_TOKEN:
            instance.status = BotPlatformInstance.Status.AWAITING_TOKEN
            instance.acquisition_mode = self.acquisition_mode
            instance.save(update_fields=["status", "acquisition_mode", "updated_at"])

        return AcquisitionResult(
            AcquisitionOutcome.AWAITING_CUSTOMER,
            {"instance": str(instance.public_id), "platform": instance.platform},
        )

    def release(self, instance: BotPlatformInstance) -> None:
        # Nothing was reserved on our side; the customer keeps their own bot.
        return None


class MtprotoRefillStrategy:
    """Tier C — operations only, feature-flagged, never on a customer request path.

    Kept behind the same interface so the ops tooling shares the saga's bookkeeping, but
    it exists to *restock the pool*, not to serve an order. A banned driving account
    would otherwise halt provisioning platform-wide mid-order (ADR-0002, rejected option).
    """

    slug = "mtproto"
    acquisition_mode = AcquisitionMode.MTPROTO

    def acquire(self, instance: BotPlatformInstance) -> AcquisitionResult:
        if not settings.PROVISIONING_MTPROTO_ENABLED:
            raise ConflictError(
                code="provisioning.mtproto_disabled",
                message="MTProto provisioning is disabled.",
            )
        raise ConflictError(
            code="provisioning.mtproto_not_on_customer_path",
            message=(
                "MTProto automation refills the pool; it never provisions a customer "
                "order directly. Use the pool or token-handoff strategy."
            ),
        )

    def release(self, instance: BotPlatformInstance) -> None:
        return None


_STRATEGIES: dict[str, ProvisioningStrategy] = {
    PoolAssignmentStrategy.slug: PoolAssignmentStrategy(),
    TokenHandoffStrategy.slug: TokenHandoffStrategy(),
    MtprotoRefillStrategy.slug: MtprotoRefillStrategy(),
}

DEFAULT_STRATEGY = PoolAssignmentStrategy.slug


def get_strategy(slug: str) -> ProvisioningStrategy:
    try:
        return _STRATEGIES[slug]
    except KeyError as exc:
        raise ConflictError(
            code="provisioning.unknown_strategy",
            message=f"Unknown provisioning strategy {slug!r}.",
        ) from exc


def strategy_for_order(order) -> str:
    """Pick the tier for an order.

    Explicit choice on the order wins; otherwise fall back to the platform default so a
    customer who expressed no preference still gets the instant experience.
    """
    chosen = (getattr(order, "provisioning_strategy", "") or "").strip()
    if chosen in _STRATEGIES:
        return chosen

    from apps.core.models import SystemSetting

    setting = SystemSetting.objects.filter(key="provisioning_default_strategy").first()
    candidate = (setting.value if setting else "") or DEFAULT_STRATEGY
    return candidate if candidate in _STRATEGIES else DEFAULT_STRATEGY
