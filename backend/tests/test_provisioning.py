"""The provisioning saga (ADR-0002, BOT_RUNTIME.md §11)."""

from __future__ import annotations

import pytest

from apps.bots.models import Bot, BotPlatformInstance, BotPoolEntry, BotStatus
from apps.core.errors import ConflictError
from apps.orders.domain.state_machine import OrderStatus
from apps.provisioning.models import JobStatus, ProvisioningJob, StepStatus
from apps.provisioning.saga import compensate, create_job, run_job

pytestmark = pytest.mark.django_db


class TestPoolStrategy:
    def test_a_paid_order_produces_a_live_bot(self, paid_order, pool_entry, fake_transport):
        """The Phase 4 exit criterion, in one test."""
        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.SUCCEEDED
        bot = job.bot
        assert bot.status == BotStatus.ACTIVE

        instance = bot.instances.get(platform="telegram")
        assert instance.status == BotPlatformInstance.Status.ACTIVE
        assert instance.username == "demo_clinic_bot"
        assert instance.link == "https://t.me/demo_clinic_bot"

        paid_order.refresh_from_db()
        assert paid_order.status == OrderStatus.ACTIVE.value

    def test_the_pool_entry_is_consumed(self, paid_order, pool_entry, fake_transport):
        run_job(create_job(order=paid_order, strategy="pool"))

        pool_entry.refresh_from_db()
        assert pool_entry.status == BotPoolEntry.Status.ASSIGNED
        assert pool_entry.assigned_instance is not None

    def test_the_customer_does_nothing(self, paid_order, pool_entry, fake_transport):
        """Tier A is zero-touch: no step should block on a human."""
        job = run_job(create_job(order=paid_order, strategy="pool"))
        assert not job.steps.filter(status=StepStatus.BLOCKED).exists()

    def test_an_empty_pool_fails_loudly(self, paid_order, fake_transport):
        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.FAILED
        assert job.error_code == "provisioning.pool_empty"

        paid_order.refresh_from_db()
        assert paid_order.status == OrderStatus.FAILED.value

    def test_the_platform_was_actually_configured(self, paid_order, pool_entry, fake_transport):
        run_job(create_job(order=paid_order, strategy="pool"))

        assert fake_transport.called("getMe")
        assert fake_transport.called("setMyName")
        assert fake_transport.called("setMyCommands")
        assert fake_transport.called("setWebhook")

    def test_the_webhook_carries_a_secret(self, paid_order, pool_entry, fake_transport):
        run_job(create_job(order=paid_order, strategy="pool"))

        payload = fake_transport.payload_for("setWebhook")
        assert payload["secret_token"]
        assert payload["url"].endswith("/")
        assert "/webhooks/telegram/" in payload["url"]

    def test_commands_reflect_the_purchased_features(
        self, paid_order, pool_entry, fake_transport
    ):
        """A /book command on a bot with no appointment feature is a support ticket."""
        run_job(create_job(order=paid_order, strategy="pool"))

        commands = {c["command"] for c in fake_transport.payload_for("setMyCommands")["commands"]}
        assert {"start", "menu", "help"} <= commands
        assert "faq" in commands  # bought
        assert "book" not in commands  # not bought


class TestIdempotenceAndResume:
    def test_creating_a_job_twice_returns_the_same_job(self, paid_order):
        first = create_job(order=paid_order)
        second = create_job(order=paid_order)
        assert first.pk == second.pk

    def test_a_duplicate_paid_event_does_not_create_two_bots(
        self, paid_order, pool_entry, fake_transport
    ):
        """Celery is at-least-once, so this *will* happen in production."""
        run_job(create_job(order=paid_order, strategy="pool"))
        run_job(create_job(order=paid_order, strategy="pool"))

        assert Bot.objects.filter(origin_order=paid_order).count() == 1

    def test_a_retry_resumes_rather_than_replaying(
        self, paid_order, pool_entry, fake_transport
    ):
        job = create_job(order=paid_order, strategy="pool")
        run_job(job)

        before = {s.step_slug: s.attempt for s in job.steps.all()}
        run_job(job)
        after = {s.step_slug: s.attempt for s in job.steps.all()}

        # Already-succeeded steps are skipped, so their attempt counts do not move.
        assert before == after

    def test_a_failure_partway_through_keeps_earlier_work(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["setWebhook"] = PlatformApiError("boom", status_code=500)
        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.FAILED
        # The bot created at step 1 survives; a retry will resume from set_webhook.
        assert Bot.objects.filter(origin_order=paid_order).exists()
        assert job.steps.get(step_slug="verify_get_me").status == StepStatus.SUCCEEDED
        assert job.steps.get(step_slug="set_webhook").status == StepStatus.FAILED

    def test_a_resumed_job_completes(self, paid_order, pool_entry, fake_transport):
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["setWebhook"] = PlatformApiError("boom", status_code=500)
        job = run_job(create_job(order=paid_order, strategy="pool"))
        assert job.status == JobStatus.FAILED

        del fake_transport.failures["setWebhook"]
        job = run_job(job)
        assert job.status == JobStatus.SUCCEEDED


class TestCompensation:
    def test_a_failed_job_returns_its_pool_entry(self, paid_order, pool_entry, fake_transport):
        """Otherwise a failure silently burns inventory."""
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["setWebhook"] = PlatformApiError("boom", status_code=500)
        job = run_job(create_job(order=paid_order, strategy="pool"))

        compensate(job)

        pool_entry.refresh_from_db()
        assert pool_entry.status == BotPoolEntry.Status.AVAILABLE
        assert pool_entry.assigned_instance is None


class TestTokenHandoff:
    def test_it_waits_for_the_customer_instead_of_failing(self, paid_order, fake_transport):
        """A paid order legitimately rests here, possibly for days (ADR-0002)."""
        job = run_job(create_job(order=paid_order, strategy="token_handoff"))

        assert job.status == JobStatus.AWAITING_CUSTOMER
        assert job.error_code == ""

        step = job.steps.get(step_slug="acquire_credential")
        assert step.status == StepStatus.BLOCKED

    def test_the_order_is_not_marked_failed_while_waiting(self, paid_order, fake_transport):
        run_job(create_job(order=paid_order, strategy="token_handoff"))

        paid_order.refresh_from_db()
        assert paid_order.status != OrderStatus.FAILED.value

    def test_the_instance_asks_for_a_token(self, paid_order, fake_transport):
        job = run_job(create_job(order=paid_order, strategy="token_handoff"))

        instance = job.bot.instances.get(platform="telegram")
        assert instance.status == BotPlatformInstance.Status.AWAITING_TOKEN

    def test_supplying_the_token_completes_provisioning(self, paid_order, fake_transport):
        from apps.bots.credentials import store_token

        job = run_job(create_job(order=paid_order, strategy="token_handoff"))
        instance = job.bot.instances.get(platform="telegram")

        store_token(instance=instance, token="7000000009:AA-customer-token-bbbbbbbbbbbbbbbbbb")

        job = run_job(job)
        assert job.status == JobStatus.SUCCEEDED
        assert job.bot.status == BotStatus.ACTIVE


class TestMtproto:
    def test_it_is_never_available_on_the_customer_path(self, paid_order, fake_transport):
        """A banned driving account must not be able to halt paid orders."""
        job = run_job(create_job(order=paid_order, strategy="mtproto"))
        assert job.status == JobStatus.FAILED
        assert "mtproto" in job.error_code


class TestPlatformCoverage:
    """Phase 5 changed this deliberately: Bale now has a provisioner, so a Bale channel
    is genuinely provisioned rather than skipped. The *deferral* mechanism still exists
    for any channel that has no provisioner yet.
    """

    def _dual_order(self, tenant_a, user):
        from apps.orders.domain.state_machine import Actor
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order

        quote, _ = build_quote(
            template_slug="clinic",
            platforms=["telegram", "bale"],
            feature_slugs=["faq"],
            currency="USD",
            business_draft={"name": "Dual Clinic"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target, actor in (
            (OrderStatus.RECEIPT_SUBMITTED, Actor.CUSTOMER),
            (OrderStatus.PAYMENT_REVIEW, Actor.STAFF),
            (OrderStatus.PAID, Actor.STAFF),
        ):
            transition_order(
                order=order, target=target, actor_type=actor, user=user, scopes={"*"}
            )
        return order

    def test_bale_now_provisions_instead_of_being_skipped(
        self, catalogue, tenant_a, user, pool_entry, fake_transport
    ):
        from apps.bots.credentials import add_pool_entry

        add_pool_entry(
            platform="bale",
            username="dual_clinic_bale_bot",
            token="7200000001:AA-bale-pool-token-bbbbbbbbbbbbbb",
        )
        order = self._dual_order(tenant_a, user)

        job = run_job(create_job(order=order, strategy="pool"))

        assert job.status == JobStatus.SUCCEEDED
        for platform in ("telegram", "bale"):
            instance = job.bot.instances.get(platform=platform)
            assert instance.status == BotPlatformInstance.Status.ACTIVE, platform

    def test_an_empty_bale_pool_is_now_a_real_failure(
        self, catalogue, tenant_a, user, pool_entry, fake_transport
    ):
        """Once a platform is supported, missing stock is a genuine problem to fix —
        not something to quietly skip past.
        """
        order = self._dual_order(tenant_a, user)

        job = run_job(create_job(order=order, strategy="pool"))

        assert job.status == JobStatus.FAILED
        assert job.error_code == "provisioning.pool_empty"


class TestErrorCodeNormalization:
    """`error_code` must be a small, closed vocabulary — RUNBOOK.md exists precisely
    because every code a job can carry is enumerable (`PROVISIONING_ERROR_CODES`, Phase
    10). A raw Python exception class name leaking through would defeat that: it isn't
    stable (renaming the class silently changes the "code") and isn't enumerable ahead of
    time."""

    def test_a_platform_api_error_normalizes_instead_of_leaking_the_class_name(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["setWebhook"] = PlatformApiError("boom", status_code=500)
        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.FAILED
        assert job.error_code == "provisioning.platform_api_error"
        assert "boom" in job.error_detail  # the detail still carries the real message

    def test_every_code_in_the_closed_set_is_a_dotted_string(self):
        from apps.provisioning.saga import PROVISIONING_ERROR_CODES

        assert len(PROVISIONING_ERROR_CODES) == len(set(PROVISIONING_ERROR_CODES))
        for code in PROVISIONING_ERROR_CODES:
            assert "." in code

    def test_normalize_error_code_directly(self):
        from apps.bots.credentials import CredentialError
        from apps.core.errors import ConflictError
        from apps.platforms.transport import PlatformApiError
        from apps.provisioning.saga import _normalize_error_code

        assert _normalize_error_code(ConflictError(code="provisioning.pool_empty")) == "provisioning.pool_empty"
        assert _normalize_error_code(CredentialError("boom")) == "provisioning.credential_error"
        assert _normalize_error_code(PlatformApiError("boom")) == "provisioning.platform_api_error"
        assert _normalize_error_code(KeyError("boom")) == "provisioning.unexpected_error"

    def test_a_platform_without_a_provisioner_is_still_deferred(self):
        """The mechanism that carried Bale through Phase 4 remains, for the next channel."""
        from apps.provisioning.provisioners import get_provisioner, supported_platforms

        assert get_provisioner("telegram") is not None
        assert get_provisioner("bale") is not None
        assert get_provisioner("whatsapp") is None
        assert supported_platforms() == {"telegram", "bale"}


class TestSeedCollectedContent:
    """Content typed into the builder's per-feature configuration step (Phase 10.5)
    becomes real data the moment the bot activates — `business_snapshot.feature_config`
    -> real `FaqEntry` rows, via `apps.provisioning.saga.step_seed_collected_content`."""

    def test_faq_drafted_before_payment_is_live_the_moment_the_bot_activates(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.businesses.models import FaqEntry

        paid_order.business_snapshot = {
            **paid_order.business_snapshot,
            "feature_config": {
                "faq": [
                    {"question": "Do you take walk-ins?", "answer": "Yes, until 6pm."},
                    {"question": "Is parking available?", "answer": "Yes, free lot next door."},
                ]
            },
        }
        paid_order.save(update_fields=["business_snapshot"])

        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.SUCCEEDED
        entries = list(FaqEntry.objects.filter(bot=job.bot).order_by("sort_order"))
        assert [e.question for e in entries] == [
            "Do you take walk-ins?",
            "Is parking available?",
        ]
        assert entries[0].answer == "Yes, until 6pm."
        assert entries[0].source == FaqEntry.Source.MANUAL

    def test_re_validates_rather_than_trusting_the_snapshot_as_already_clean(
        self, paid_order, pool_entry, fake_transport
    ):
        """The saga step must hold even if whatever wrote `business_snapshot` skipped
        `BuildQuoteSerializer`'s cleaning — a raw, over-length, unvalidated blob here
        must not reach the database unclean."""
        from apps.businesses.models import FaqEntry

        paid_order.business_snapshot = {
            **paid_order.business_snapshot,
            "feature_config": {
                "faq": [
                    {"question": "Q with no answer at all"},  # missing required field
                    {"question": "Q2", "answer": "x" * 5000},  # far past max_length
                ]
            },
        }
        paid_order.save(update_fields=["business_snapshot"])

        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.SUCCEEDED
        entries = list(FaqEntry.objects.filter(bot=job.bot))
        assert len(entries) == 1  # the incomplete item was dropped, not saved half-written
        assert len(entries[0].answer) == 2000  # truncated to the schema's max_length

    def test_a_resumed_job_does_not_duplicate_faq_entries(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.businesses.models import FaqEntry
        from apps.provisioning.saga import StepContext, step_seed_collected_content

        paid_order.business_snapshot = {
            **paid_order.business_snapshot,
            "feature_config": {"faq": [{"question": "Q", "answer": "A"}]},
        }
        paid_order.save(update_fields=["business_snapshot"])

        job = run_job(create_job(order=paid_order, strategy="pool"))
        assert FaqEntry.objects.filter(bot=job.bot).count() == 1

        # A second run of the same step, as a resume would do, must be a no-op.
        step_seed_collected_content(StepContext(job=job, order=paid_order, bot=job.bot))
        assert FaqEntry.objects.filter(bot=job.bot).count() == 1

    def test_no_feature_config_is_a_harmless_no_op(self, paid_order, pool_entry, fake_transport):
        """`paid_order`'s own draft has no `feature_config` key at all — the common case
        (a customer who added no FAQ content) must provision cleanly, not error."""
        job = run_job(create_job(order=paid_order, strategy="pool"))
        assert job.status == JobStatus.SUCCEEDED

    def test_property_listings_drafted_before_payment_are_live_on_activation(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.commerce.models import PropertyListing

        paid_order.features = [*paid_order.features, "property_listings"]
        paid_order.business_snapshot = {
            **paid_order.business_snapshot,
            "feature_config": {
                "property_listings": [
                    {
                        "title": "2-bed downtown",
                        "listing_type": "RENT",
                        "property_type": "APARTMENT",
                        "price": "250000",
                        "address": "12 Example Street",
                    },
                    {  # unparseable price -> dropped, not priced as free
                        "title": "Broken listing",
                        "listing_type": "SALE",
                        "property_type": "HOUSE",
                        "price": "not-a-number",
                    },
                ]
            },
        }
        paid_order.save(update_fields=["features", "business_snapshot"])

        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.SUCCEEDED
        listings = list(PropertyListing.objects.filter(bot=job.bot))
        assert len(listings) == 1
        assert listings[0].title == "2-bed downtown"
        assert listings[0].listing_type == "RENT"
        assert listings[0].price_minor == 250_000_00

    def test_course_offerings_drafted_before_payment_are_live_on_activation(
        self, paid_order, pool_entry, fake_transport
    ):
        from apps.commerce.models import CourseOffering

        paid_order.features = [*paid_order.features, "course_catalog"]
        paid_order.business_snapshot = {
            **paid_order.business_snapshot,
            "feature_config": {
                "course_catalog": [
                    {"title": "Beginner Photoshop", "price": "199.99", "instructor_name": "Dana"},
                ]
            },
        }
        paid_order.save(update_fields=["features", "business_snapshot"])

        job = run_job(create_job(order=paid_order, strategy="pool"))

        assert job.status == JobStatus.SUCCEEDED
        courses = list(CourseOffering.objects.filter(bot=job.bot))
        assert len(courses) == 1
        assert courses[0].title == "Beginner Photoshop"
        assert courses[0].instructor_name == "Dana"
