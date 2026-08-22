"""The provisioning saga.

Ordered, individually-idempotent steps. A retry resumes at the first step that is not
`SUCCEEDED`; steps that already ran are skipped, not replayed. This is why provisioning
survives a worker crash halfway through without creating two bots or losing a pool entry.

One state deserves special mention: `AWAITING_CUSTOMER`. Under tier B a paid order sits
here until the customer pastes a token — possibly for days. That is a legitimate resting
state, not a failure, and nothing in this file times it out (ADR-0002).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.bots import credentials as credential_service
from apps.bots.models import (
    Bot,
    BotConfiguration,
    BotFeature,
    BotPlatformInstance,
    BotStatus,
    WebhookSecret,
)
from apps.businesses.models import BusinessProfile
from apps.core.errors import AppError, ConflictError
from apps.core.events import publish
from apps.core.metrics import PROVISIONING_JOB_TOTAL
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.models import Order
from apps.orders.services import transition_order
from apps.provisioning.models import JobStatus, ProvisioningJob, ProvisioningStep, StepStatus
from apps.provisioning.provisioners import get_provisioner
from apps.provisioning.strategies import (
    AcquisitionOutcome,
    get_strategy,
    strategy_for_order,
)

logger = logging.getLogger(__name__)


@dataclass
class StepContext:
    job: ProvisioningJob
    order: Order
    bot: Bot | None = None


#: Signal from a step that the saga should pause rather than fail.
class AwaitingCustomer(Exception):
    def __init__(self, detail: dict | None = None) -> None:
        self.detail = detail or {}
        super().__init__("Waiting for the customer to supply a bot token.")


# --------------------------------------------------------------------------- steps


def step_create_bot_record(ctx: StepContext) -> dict:
    """Create the Bot, its configuration, features and one instance per platform."""
    order = ctx.order

    bot = Bot.objects.filter(origin_order=order).first()
    if bot is None:
        business = order.business_snapshot or {}
        bot = Bot.objects.create(
            tenant=order.tenant,
            origin_order=order,
            template=order.template,
            name=(business.get("name") or f"{order.template.name} bot")[:128],
            status=BotStatus.PROVISIONING,
            default_locale=order.locale,
            timezone=order.tenant.timezone,
            currency=order.currency,
        )

    BotConfiguration.objects.get_or_create(
        bot=bot,
        defaults={
            "welcome_message": (order.business_snapshot or {}).get("welcome_message", ""),
            "branding": {"business": order.business_snapshot or {}},
        },
    )

    # The live, editable record (spec §24) — seeded from what the customer typed in the
    # builder. `branding['business']` above stays too, as the fallback `context.py`
    # reads if this row is ever missing; the profile is the one a dashboard edit changes.
    business = order.business_snapshot or {}
    BusinessProfile.objects.get_or_create(
        bot=bot,
        defaults={
            "tenant": bot.tenant,
            "display_name": (business.get("name") or bot.name)[:255],
            "description": business.get("description", ""),
            "phone": business.get("phone", "")[:32],
            "email": business.get("email", "")[:254],
            "address": business.get("address", "")[:255],
            "working_hours_text": business.get("working_hours", "")[:255],
        },
    )

    for platform in order.platforms:
        BotPlatformInstance.objects.get_or_create(
            bot=bot,
            platform=platform,
            defaults={"acquisition_mode": get_strategy(ctx.job.strategy).acquisition_mode},
        )

    ctx.bot = bot
    ctx.job.bot = bot
    ctx.job.save(update_fields=["bot", "updated_at"])
    return {"bot": str(bot.public_id), "instances": len(order.platforms)}


def step_enable_features(ctx: StepContext) -> dict:
    """Turn the purchased features on. Driven by the order, not by the template."""
    from apps.features.models import Feature

    bot = _require_bot(ctx)
    enabled = 0
    for slug in ctx.order.features:
        feature = Feature.objects.filter(slug=slug, is_active=True).first()
        if feature is None:
            continue
        _, created = BotFeature.objects.get_or_create(
            bot=bot,
            feature=feature,
            defaults={"is_enabled": True, "enabled_at": timezone.now()},
        )
        enabled += int(created)
    return {"features": len(ctx.order.features), "newly_enabled": enabled}


def step_seed_collected_content(ctx: StepContext) -> dict:
    """Materialize content the customer typed into the builder's per-feature
    configuration steps (dynamic configuration, Phase 10.5) — before this, that content
    only existed as a draft on the quote/order; this is what turns it into real, live
    rows the moment the bot activates, not something the customer has to re-enter from
    the management panel after paying.

    Re-validates against each feature's own `CollectSchema` rather than trusting
    `business_snapshot` as already-clean — `BuildQuoteSerializer.validate()` cleans it
    once at quote-build time, but this step must hold regardless of what wrote the
    snapshot (a future non-web ordering path, a resumed job, a hand-edited fixture).
    """
    from apps.businesses.services import create_faq_entry
    from apps.commerce.services import create_course, create_property
    from apps.core.formatting import get_exponent
    from apps.core.money import Money
    from apps.features.manifests import validate_collected_items
    from apps.features.registry import all_manifests

    bot = _require_bot(ctx)
    feature_config = (ctx.order.business_snapshot or {}).get("feature_config") or {}
    manifests = all_manifests()
    created_counts: dict[str, int] = {}

    def _items_for(slug: str) -> list[dict[str, str]]:
        if slug not in feature_config or slug not in ctx.order.features:
            return []
        manifest = manifests.get(slug)
        if manifest is None or manifest.collects is None:
            return []
        return validate_collected_items(manifest.collects, feature_config[slug])

    def _price_minor(raw: str) -> int | None:
        """A customer types a price in normal terms ("250000", "199.99") — parsed
        against the bot's own currency exponent, same conversion `Money.from_major`
        already does everywhere else in this codebase. `None` (not zero) for anything
        unparseable, so a typo drops just that one item rather than pricing it free."""
        from decimal import InvalidOperation

        try:
            return Money.from_major(raw, bot.currency, get_exponent(bot.currency)).amount_minor
        except (InvalidOperation, ValueError):
            return None

    if "faq" in feature_config and "faq" in ctx.order.features:
        # Idempotent by presence, like the rest of this step's siblings' `get_or_create`
        # calls — a resumed run must not duplicate entries a prior attempt already wrote.
        if not bot.faq_entries.exists():
            items = _items_for("faq")
            for index, item in enumerate(items):
                create_faq_entry(
                    bot=bot,
                    actor=None,
                    question=item["question"],
                    answer=item["answer"],
                    sort_order=index * 10,
                )
            created_counts["faq"] = len(items)

    if not bot.property_listings.exists():
        items = _items_for("property_listings")
        made = 0
        for index, item in enumerate(items):
            price_minor = _price_minor(item.get("price", ""))
            if price_minor is None:
                continue
            create_property(
                bot=bot,
                actor=None,
                title=item["title"],
                listing_type=item["listing_type"],
                property_type=item["property_type"],
                price_minor=price_minor,
                address=item.get("address", ""),
                description=item.get("description", ""),
                sort_order=index * 10,
            )
            made += 1
        if made:
            created_counts["property_listings"] = made

    if not bot.course_offerings.exists():
        items = _items_for("course_catalog")
        made = 0
        for index, item in enumerate(items):
            price_minor = _price_minor(item.get("price", ""))
            if price_minor is None:
                continue
            create_course(
                bot=bot,
                actor=None,
                title=item["title"],
                price_minor=price_minor,
                instructor_name=item.get("instructor_name", ""),
                duration_label=item.get("duration_label", ""),
                description=item.get("description", ""),
                sort_order=index * 10,
            )
            made += 1
        if made:
            created_counts["course_catalog"] = made

    return created_counts


def step_acquire_credential(ctx: StepContext) -> dict:
    """Obtain a token for every instance, per the order's strategy."""
    bot = _require_bot(ctx)
    strategy = get_strategy(ctx.job.strategy)

    acquired, waiting, deferred = [], [], []
    for instance in _provisionable_instances(bot, deferred):
        if hasattr(instance, "credential"):
            acquired.append(instance.platform)
            continue

        result = strategy.acquire(instance)
        if result.outcome == AcquisitionOutcome.AWAITING_CUSTOMER:
            waiting.append(instance.platform)
        else:
            acquired.append(instance.platform)

    if waiting:
        raise AwaitingCustomer({"platforms": waiting})

    return {"acquired": acquired, "deferred": deferred}


def step_verify_get_me(ctx: StepContext) -> dict:
    """Validate each token and capture the bot's real identity."""
    bot = _require_bot(ctx)
    verified = []

    for instance in _provisionable_instances(bot):
        provisioner = get_provisioner(instance.platform)
        token = credential_service.read_token(instance=instance, purpose="verify_get_me")
        identity = provisioner.verify(token)

        instance.platform_bot_id = identity.platform_bot_id
        instance.username = identity.username
        instance.display_name = identity.display_name
        instance.status = BotPlatformInstance.Status.CONFIGURING
        instance.save(
            update_fields=[
                "platform_bot_id",
                "username",
                "display_name",
                "status",
                "updated_at",
            ]
        )
        verified.append(f"{instance.platform}:@{identity.username}")

    return {"verified": verified}


def step_apply_configuration(ctx: StepContext) -> dict:
    """Push the customer's branding to the platform."""
    bot = _require_bot(ctx)
    business = (ctx.order.business_snapshot or {})
    description = (business.get("description") or "")[:512]
    applied = []

    for instance in _provisionable_instances(bot):
        provisioner = get_provisioner(instance.platform)
        token = credential_service.read_token(instance=instance, purpose="apply_configuration")
        provisioner.apply_branding(
            token,
            name=bot.name,
            description=description,
            short=description[:120],
        )
        applied.append(instance.platform)

    return {"applied": applied}


def step_set_commands(ctx: StepContext) -> dict:
    """Register the localized command list."""
    from apps.provisioning.commands import command_list_for

    bot = _require_bot(ctx)
    applied = []

    for instance in _provisionable_instances(bot):
        provisioner = get_provisioner(instance.platform)
        token = credential_service.read_token(instance=instance, purpose="set_commands")

        for locale in {bot.default_locale, *settings.ACTIVE_LOCALES}:
            commands = command_list_for(bot, locale)
            if commands:
                provisioner.set_commands(
                    token,
                    commands,
                    language_code="" if locale == bot.default_locale else locale,
                )
        applied.append(instance.platform)

    return {"applied": applied}


def step_set_webhook(ctx: StepContext) -> dict:
    """Generate a per-bot secret and register the webhook."""
    bot = _require_bot(ctx)
    registered = []

    for instance in _provisionable_instances(bot):
        provisioner = get_provisioner(instance.platform)
        secret = rotate_webhook_secret(instance)
        url = webhook_url_for(instance)

        token = credential_service.read_token(instance=instance, purpose="set_webhook")
        provisioner.set_webhook(token, url, secret)

        instance.webhook_url = url
        instance.webhook_set_at = timezone.now()
        instance.save(update_fields=["webhook_url", "webhook_set_at", "updated_at"])
        registered.append(instance.platform)

    return {"registered": registered}


def step_smoke_test(ctx: StepContext) -> dict:
    """Prove the bot answers before telling the customer it is ready.

    Runs a synthetic `/start` through the *real* dispatcher, so a bot that provisions
    cleanly but cannot actually reply is caught here rather than by the customer.
    """
    from apps.bot_runtime.dispatcher import simulate_start

    bot = _require_bot(ctx)
    results = []
    for instance in _provisionable_instances(bot):
        rendered = simulate_start(instance)
        if not rendered or not rendered.text:
            raise ConflictError(
                code="provisioning.smoke_test_failed",
                message=f"The bot produced no reply to /start on {instance.platform}.",
            )
        results.append({"platform": instance.platform, "reply_length": len(rendered.text)})
    return {"smoke": results}


def step_activate(ctx: StepContext) -> dict:
    """Flip the bot and its order live."""
    bot = _require_bot(ctx)
    deferred: list[str] = []

    for instance in _provisionable_instances(bot, deferred):
        instance.status = BotPlatformInstance.Status.ACTIVE
        instance.save(update_fields=["status", "updated_at"])

    bot.status = BotStatus.ACTIVE
    bot.save(update_fields=["status", "updated_at"])

    order = Order.objects.get(pk=ctx.order.pk)
    if order.status != OrderStatus.ACTIVE.value:
        transition_order(
            order=order,
            target=OrderStatus.ACTIVE,
            actor_type=Actor.SYSTEM,
            reason="Bot activated",
            metadata={"bot": str(bot.public_id)},
        )

    from apps.subscriptions.services import start as start_subscription

    start_subscription(bot=bot, order=order)

    return {"bot": str(bot.public_id), "deferred_platforms": deferred}


def step_addon_bind_bot(ctx: StepContext) -> dict:
    """Point the job at the existing bot rather than creating one.

    The add-on saga (spec §24 "customers can add features later") never touches
    credentials, webhooks or branding — all of that is already live. It only has to
    enable the newly bought features and refresh what the platform advertises.
    """
    bot = ctx.order.target_bot
    if bot is None:
        raise ConflictError(
            code="provisioning.no_target_bot",
            message="An add-on order must name the bot it applies to.",
        )
    ctx.bot = bot
    ctx.job.bot = bot
    ctx.job.save(update_fields=["bot", "updated_at"])
    return {"bot": str(bot.public_id)}


def step_addon_activate(ctx: StepContext) -> dict:
    """Invalidate the runtime cache and close out the order.

    The bot was already `ACTIVE`; nothing about its own status changes. Bumping the
    configuration version is what makes the new feature's menu entry appear on the very
    next message, rather than after the cache TTL.
    """
    bot = _require_bot(ctx)
    bot.configuration.bump()

    order = Order.objects.get(pk=ctx.order.pk)
    if order.status != OrderStatus.ACTIVE.value:
        transition_order(
            order=order,
            target=OrderStatus.ACTIVE,
            actor_type=Actor.SYSTEM,
            reason="Features activated",
            metadata={"bot": str(bot.public_id)},
        )

    from apps.subscriptions.services import add_recurring_amount

    add_recurring_amount(bot=bot, order=order)

    return {"bot": str(bot.public_id)}


@dataclass(frozen=True, slots=True)
class Step:
    slug: str
    handler: Callable[[StepContext], dict]
    #: Order status this step belongs to. The saga advances the order as it crosses
    #: boundaries, which is what drives the customer-facing progress display in
    #: spec §20 ("Creating your bot → Configuring features → Activating bot").
    order_status: OrderStatus


#: The saga, in order. Adding a step is a one-line change — existing jobs simply gain a
#: PENDING step, and a resumed run picks it up.
STEPS: tuple[Step, ...] = (
    Step("create_bot_record", step_create_bot_record, OrderStatus.PROVISIONING),
    Step("enable_features", step_enable_features, OrderStatus.PROVISIONING),
    Step("seed_collected_content", step_seed_collected_content, OrderStatus.PROVISIONING),
    Step("acquire_credential", step_acquire_credential, OrderStatus.PROVISIONING),
    Step("verify_get_me", step_verify_get_me, OrderStatus.PROVISIONING),
    Step("apply_configuration", step_apply_configuration, OrderStatus.CONFIGURING),
    Step("set_commands", step_set_commands, OrderStatus.CONFIGURING),
    Step("set_webhook", step_set_webhook, OrderStatus.DEPLOYING),
    Step("smoke_test", step_smoke_test, OrderStatus.DEPLOYING),
    Step("activate", step_activate, OrderStatus.ACTIVE),
)

#: The add-on saga: buying more features for a bot that is already live. Everything
#: about acquiring and verifying a credential, branding and the webhook is skipped —
#: it is already done — which is also why this reaches ACTIVE in four steps instead
#: of nine.
ADDON_STEPS: tuple[Step, ...] = (
    Step("addon_bind_bot", step_addon_bind_bot, OrderStatus.PROVISIONING),
    Step("enable_features", step_enable_features, OrderStatus.PROVISIONING),
    # `seed_collected_content` deliberately omitted: nothing today gives an add-on order
    # a `feature_config` to seed (`AddonFeaturesPanel` is a plain checkout, not a
    # configuration wizard) — adding a step with no real caller would just dilute this
    # saga's intentionally minimal four steps for a benefit that doesn't exist yet. Add
    # it here the day an add-on purchase actually collects per-feature content.
    # Tagged DEPLOYING, not CONFIGURING: the state machine has no CONFIGURING → ACTIVE
    # edge, only CONFIGURING → DEPLOYING → ACTIVE. This is what makes `_advance_order_to`
    # walk the order all the way to DEPLOYING before `addon_activate` closes it out.
    Step("set_commands", step_set_commands, OrderStatus.DEPLOYING),
    Step("addon_activate", step_addon_activate, OrderStatus.ACTIVE),
)


def _steps_for(order: Order) -> tuple[Step, ...]:
    from apps.orders.models import OrderKind

    return ADDON_STEPS if order.kind == OrderKind.ADDON else STEPS


# --------------------------------------------------------------------------- helpers


def _require_bot(ctx: StepContext) -> Bot:
    if ctx.bot is None:
        ctx.bot = ctx.job.bot
    if ctx.bot is None:
        raise ConflictError(
            code="provisioning.no_bot", message="The bot record has not been created yet."
        )
    return ctx.bot


def _provisionable_instances(bot: Bot, deferred: list[str] | None = None):
    """Instances whose platform has a registered provisioner.

    Platforms without one (Bale until Phase 5) are reported as deferred and skipped —
    they must not block the channels that are ready.
    """
    for instance in bot.instances.all().order_by("platform"):
        if get_provisioner(instance.platform) is None:
            if deferred is not None:
                deferred.append(instance.platform)
            continue
        yield instance


def rotate_webhook_secret(instance: BotPlatformInstance) -> str:
    """Issue a fresh secret, leaving the previous one valid briefly.

    Two secrets may be accepted at once so rotation never drops an update that is
    already in flight (BOT_RUNTIME.md §2).
    """
    secret = secrets.token_urlsafe(32)
    WebhookSecret.objects.create(
        instance=instance,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        is_active=True,
    )
    # Retire anything older than the two most recent.
    stale = WebhookSecret.objects.filter(instance=instance, is_active=True).order_by(
        "-valid_from"
    )[2:]
    WebhookSecret.objects.filter(pk__in=[s.pk for s in stale]).update(
        is_active=False, valid_to=timezone.now()
    )
    return secret


def webhook_url_for(instance: BotPlatformInstance) -> str:
    base = settings.PUBLIC_WEBHOOK_BASE_URL.rstrip("/")
    return f"{base}/webhooks/{instance.platform}/{instance.public_id}/"


# --------------------------------------------------------------------------- runner


@transaction.atomic
def create_job(*, order: Order, strategy: str | None = None) -> ProvisioningJob:
    """Create (or return) the saga for an order. Idempotent per order."""
    key = f"order:{order.public_id}"
    existing = ProvisioningJob.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing

    job = ProvisioningJob.objects.create(
        order=order,
        strategy=strategy or strategy_for_order(order),
        idempotency_key=key,
        status=JobStatus.QUEUED,
    )
    ProvisioningStep.objects.bulk_create(
        [
            ProvisioningStep(job=job, step_slug=step.slug, sequence=index * 10)
            for index, step in enumerate(_steps_for(order))
        ]
    )
    return job


def run_job(job: ProvisioningJob) -> ProvisioningJob:
    """Execute the saga from the first unfinished step.

    Not wrapped in a single transaction: each step commits on its own so a failure at
    step 7 does not roll back the bot created at step 1, and the retry can resume.
    """
    job.attempt += 1
    job.status = JobStatus.RUNNING
    job.started_at = job.started_at or timezone.now()
    job.error_code = ""
    job.error_detail = ""
    job.save(update_fields=["attempt", "status", "started_at", "error_code", "error_detail", "updated_at"])

    order = job.order
    ctx = StepContext(job=job, order=order, bot=job.bot)

    # A retry starts from a FAILED order. The state machine's only exit from FAILED is
    # back to PROVISIONING, which is exactly what a retry means — take that edge before
    # resuming, or every later transition is illegal.
    order.refresh_from_db(fields=["status"])
    if order.status == OrderStatus.FAILED.value:
        transition_order(
            order=order,
            target=OrderStatus.PROVISIONING,
            actor_type=Actor.SYSTEM,
            reason="Provisioning retried",
        )
        if job.bot_id:
            Bot.objects.filter(pk=job.bot_id).update(status=BotStatus.PROVISIONING)

    for step_def in _steps_for(order):
        slug, handler = step_def.slug, step_def.handler
        step = job.steps.get(step_slug=slug)
        if step.status == StepStatus.SUCCEEDED:
            continue  # resumed run — do not replay

        step.status = StepStatus.RUNNING
        step.attempt += 1
        step.started_at = timezone.now()
        step.save(update_fields=["status", "attempt", "started_at", "updated_at"])

        try:
            # Walk the order forward as the saga crosses phase boundaries. `activate`
            # moves the order itself, so it is excluded here. Inside the try, not
            # before it: a failure here (an illegal/forbidden transition) must land a
            # real `error_code` on the job like every other step failure, not escape
            # `run_job` uncaught and leave it stuck `RUNNING` with none at all.
            if step_def.order_status is not OrderStatus.ACTIVE:
                _advance_order_to(order, step_def.order_status)
            output = handler(ctx)
        except AwaitingCustomer as pause:
            step.status = StepStatus.BLOCKED
            step.output = pause.detail
            step.finished_at = timezone.now()
            step.save(update_fields=["status", "output", "finished_at", "updated_at"])

            job.status = JobStatus.AWAITING_CUSTOMER
            job.save(update_fields=["status", "updated_at"])
            logger.info("Provisioning job %s is waiting for the customer", job.public_id)
            publish(
                "provisioning.awaiting_customer",
                {
                    "order_id": str(order.public_id),
                    "number": order.number,
                    "tenant_id": str(order.tenant.public_id),
                    "platforms": pause.detail.get("platforms", []),
                },
            )
            return job
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = f"{type(exc).__name__}: {exc}"[:2000]
            step.finished_at = timezone.now()
            step.save(update_fields=["status", "error", "finished_at", "updated_at"])

            _fail(job, order, code=_normalize_error_code(exc), detail=str(exc))
            logger.exception("Provisioning step %s failed for job %s", slug, job.public_id)
            return job

        step.status = StepStatus.SUCCEEDED
        step.output = output
        step.finished_at = timezone.now()
        step.save(update_fields=["status", "output", "finished_at", "updated_at"])

    job.status = JobStatus.SUCCEEDED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    PROVISIONING_JOB_TOTAL.labels(status="succeeded", error_code="").inc()

    record_audit(
        actor=None,
        action="provisioning.succeeded",
        resource_type="provisioning_job",
        resource_id=str(job.public_id),
        tenant=order.tenant,
        metadata={"order": order.number, "strategy": job.strategy},
    )
    return job


#: The provisioning phases, in the order the state machine allows.
_PROVISIONING_SEQUENCE = (
    OrderStatus.PROVISIONING,
    OrderStatus.CONFIGURING,
    OrderStatus.DEPLOYING,
)


def _advance_order_to(order: Order, target: OrderStatus) -> None:
    """Step the order forward to `target`, one legal transition at a time.

    The state machine has no shortcuts — `PROVISIONING → ACTIVE` is not an edge — so a
    saga that jumps phases would be rejected. Walking the sequence is also what gives
    the customer real progress rather than a spinner.
    """
    order.refresh_from_db(fields=["status"])
    current = OrderStatus(order.status)

    if current not in {OrderStatus.PAID, *_PROVISIONING_SEQUENCE}:
        return  # already ACTIVE, or failed/cancelled — nothing to advance

    for phase in _PROVISIONING_SEQUENCE:
        order.refresh_from_db(fields=["status"])
        if OrderStatus(order.status) == target:
            return
        if _PROVISIONING_SEQUENCE.index(phase) < _phase_index(order.status):
            continue
        transition_order(
            order=order,
            target=phase,
            actor_type=Actor.SYSTEM,
            reason=f"Provisioning: {phase.value.lower()}",
        )
        if phase == target:
            return


def _phase_index(status: str) -> int:
    try:
        return _PROVISIONING_SEQUENCE.index(OrderStatus(status))
    except ValueError:
        return -1


#: Every `error_code` a `ProvisioningJob` can actually carry — closed and enumerable, so
#: an operator runbook (RUNBOOK.md) can cover all of them, not just the ones someone
#: happened to trigger while writing it. `AppError` subclasses raised anywhere in a step's
#: call graph already carry a small, stable, dotted `.code` (see the individual `raise`
#: sites in `strategies.py`, this file, and `apps.bots.credentials`); everything else is
#: normalized here rather than leaking a raw Python exception class name, which is neither
#: stable (renaming an internal exception class would silently change the "failure code")
#: nor enumerable in advance.
PROVISIONING_ERROR_CODES: tuple[str, ...] = (
    "provisioning.pool_empty",
    "provisioning.mtproto_disabled",
    "provisioning.mtproto_not_on_customer_path",
    "provisioning.unknown_strategy",
    "provisioning.no_target_bot",
    "provisioning.no_bot",
    "provisioning.smoke_test_failed",
    "bots.invalid_token",
    "bots.token_already_registered",
    "order.illegal_transition",
    "order.transition_forbidden",
    "provisioning.credential_error",
    "provisioning.platform_api_error",
    "provisioning.unexpected_error",
)


def _normalize_error_code(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.code

    from apps.bots.credentials import CredentialError
    from apps.platforms.transport import PlatformApiError

    if isinstance(exc, CredentialError):
        return "provisioning.credential_error"
    if isinstance(exc, PlatformApiError):
        return "provisioning.platform_api_error"
    return "provisioning.unexpected_error"


def _fail(job: ProvisioningJob, order: Order, *, code: str, detail: str) -> None:
    job.status = JobStatus.FAILED
    job.error_code = str(code)[:64]
    job.error_detail = detail[:2000]
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_code", "error_detail", "finished_at", "updated_at"])
    PROVISIONING_JOB_TOTAL.labels(status="failed", error_code=job.error_code).inc()

    if order.status in {
        OrderStatus.PROVISIONING.value,
        OrderStatus.CONFIGURING.value,
        OrderStatus.DEPLOYING.value,
    }:
        transition_order(
            order=order,
            target=OrderStatus.FAILED,
            actor_type=Actor.SYSTEM,
            reason=f"Provisioning failed: {code}",
        )

    if job.bot is not None:
        Bot.objects.filter(pk=job.bot_id).update(status=BotStatus.FAILED)


def compensate(job: ProvisioningJob) -> ProvisioningJob:
    """Release anything the job reserved, so a failure does not leak inventory."""
    job.status = JobStatus.COMPENSATING
    job.save(update_fields=["status", "updated_at"])

    strategy = get_strategy(job.strategy)
    if job.bot is not None:
        for instance in job.bot.instances.all():
            strategy.release(instance)

    job.status = JobStatus.COMPENSATED
    job.save(update_fields=["status", "updated_at"])
    return job
