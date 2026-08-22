"""Provision the platform's own permanent "builder" bot — the one instance the
`bot_builder` feature is enabled on, which is what lets a customer order a brand-new bot
entirely by chatting (`apps.bot_builder.handlers`).

Run once per platform, with a real BotFather (or Bale) token:

    python manage.py provision_builder_bot --platform telegram --token <token> --username my_builder_bot

Idempotent: re-running for a platform that already has an ACTIVE builder instance does
nothing (the saga's own idempotency key, `apps.provisioning.saga.create_job`, catches
that). Goes through the exact order -> payment -> provisioning saga a real customer's bot
does, rather than hand-building a `Bot` row, specifically so this inherits the saga's
retry guarantees and webhook-registration step instead of a second, parallel path that
could drift from what actually provisions a bot. There is no real payment involved — the
order is transitioned straight to PAID as the platform's own infrastructure, not a sale.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.bots import credentials as credential_service
from apps.bots.models import BotFeature, BotPlatformInstance
from apps.customers.models import Tenant, TenantMembership, TenantRole
from apps.features.manifests import FeatureCategory
from apps.features.models import Feature
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.services import build_quote, claim_quote, place_order, transition_order
from apps.provisioning.models import JobStatus
from apps.provisioning.saga import create_job, run_job

BUILDER_TENANT_SLUG = "bot-builder-platform"
BUILDER_TENANT_NAME = "Bot Builder Platform"


class Command(BaseCommand):
    help = "Provision the platform's own chat-native builder bot for one channel (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--platform", required=True, choices=["telegram", "bale"])
        parser.add_argument("--token", required=True, help="A real BotFather/Bale token for this bot.")
        parser.add_argument("--username", required=True, help="The bot's own @username, without @.")
        parser.add_argument("--currency", default="USD", help="Currency the internal order is priced in.")
        parser.add_argument(
            "--owner-email", default="", help="Staff account of record for the platform tenant (optional)."
        )

    def handle(self, *args, **options) -> None:
        platform = options["platform"]
        token = options["token"]
        username = options["username"].lstrip("@")
        currency = options["currency"].upper()
        owner_email = options["owner_email"].strip().lower()

        feature = self._ensure_feature()
        tenant = self._ensure_tenant(owner_email)

        from apps.bots.models import Bot

        existing = Bot.objects.filter(
            tenant=tenant, instances__platform=platform, instances__status="ACTIVE"
        ).first()
        if existing is not None:
            self.stdout.write(self.style.WARNING(f"Already active on {platform}: bot={existing.public_id}"))
            return

        quote, _ = build_quote(
            template_slug="generic",
            platforms=[platform],
            feature_slugs=[],
            currency=currency,
            business_draft={"name": BUILDER_TENANT_NAME},
        )
        claim_quote(quote=quote, tenant=tenant, user=None)
        order = place_order(quote=quote, tenant=tenant, user=None)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(
                order=order, target=target, actor_type=actor, user=None, scopes={"*"},
                reason="Platform-owned builder bot; no real payment.",
            )

        # "token_handoff", not "pool": this is one deliberately-chosen, never-recycled
        # bot identity, not an interchangeable instant one — the pool strategy would
        # happily hand back whichever entry is oldest, ignoring the token given here.
        job = run_job(create_job(order=order, strategy="token_handoff"))
        if job.status != JobStatus.AWAITING_CUSTOMER:
            raise CommandError(f"Unexpected job status {job.status}: {job.error_code} — {job.error_detail}")

        instance = BotPlatformInstance.objects.get(bot=job.bot, platform=platform)
        credential_service.store_token(instance=instance, token=token)
        instance.status = BotPlatformInstance.Status.CONFIGURING
        instance.save(update_fields=["status", "updated_at"])

        job = run_job(job)
        if job.status != "SUCCEEDED":
            raise CommandError(f"Provisioning failed: {job.error_code} — {job.error_detail}")

        bot = job.bot
        BotFeature.objects.update_or_create(bot=bot, feature=feature, defaults={"is_enabled": True})
        bot.configuration.bump()

        instance = bot.instances.get(platform=platform)
        self.stdout.write(
            self.style.SUCCESS(f"Builder bot live on {platform}: bot={bot.public_id} instance={instance.public_id}")
        )

    def _ensure_feature(self) -> Feature:
        feature, _ = Feature.objects.update_or_create(
            slug="bot_builder",
            defaults={
                "category": FeatureCategory.CORE,
                "icon": "hammer",
                "name": "Bot builder",
                "description": "Order a new bot by chatting.",
                # Never sold: not attached to any template, and hidden from the public
                # catalogue so it can't be confused for a purchasable feature.
                "is_active": False,
                "sort_order": 999,
            },
        )
        return feature

    def _ensure_tenant(self, owner_email: str) -> Tenant:
        tenant = Tenant.objects.filter(slug=BUILDER_TENANT_SLUG).first()
        if tenant is not None:
            return tenant

        owner = User.objects.filter(email=owner_email).first() if owner_email else None
        tenant = Tenant.objects.create(name=BUILDER_TENANT_NAME, slug=BUILDER_TENANT_SLUG, created_by=owner)
        if owner is not None:
            TenantMembership.objects.create(tenant=tenant, user=owner, role=TenantRole.OWNER)
        return tenant
