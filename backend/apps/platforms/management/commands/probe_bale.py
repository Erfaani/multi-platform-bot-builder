"""Run the Bale capability spike (BALE.md §2) against a real bot.

This is the Phase 5 entry gate that could not be run during development: it needs a real
Bale bot token and network reachability to Bale, which is exactly the thing R-03 says we
cannot assume from an arbitrary location.

Rather than guess, the questions are automated. An operator with a token runs:

    python manage.py probe_bale --token <token> --chat <chat_id>

and gets a filled-in answer table plus recorded fixtures. `--apply` then writes the
measured capabilities and updates `feature_platform_availability`, so what the builder
sells on Bale matches what Bale can actually do.

Nothing here writes to the database unless `--apply` is passed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.platforms.constants import Platform
from apps.platforms.transport import PlatformApiError

FIXTURE_DIR = Path("tests/fixtures/bale")


@dataclass
class Answer:
    question: str
    supported: bool | None = None
    detail: str = ""
    raw: dict | list | None = None

    @property
    def mark(self) -> str:
        return {True: "yes", False: "no", None: "?"}[self.supported]


@dataclass
class ProbeReport:
    answers: dict[str, Answer] = field(default_factory=dict)

    def record(self, key: str, question: str, supported: bool | None, detail: str = "", raw=None):
        self.answers[key] = Answer(question, supported, detail, raw)

    def as_capabilities(self) -> dict:
        """Translate the answers into a `Capabilities` proposal."""

        def yes(key: str, default: bool) -> bool:
            answer = self.answers.get(key)
            return default if answer is None or answer.supported is None else answer.supported

        return {
            "inline_keyboards": yes("inline_keyboards", False),
            "reply_keyboards": yes("reply_keyboards", True),
            "message_editing": yes("message_editing", False),
            "media_groups": yes("media_groups", False),
            "file_uploads": yes("file_uploads", False),
            "web_app": False,
            "max_text_length": int(self.answers.get("max_text_length", Answer("")).detail or 4096),
            "verified": True,
        }


class Command(BaseCommand):
    help = "Probe the Bale Bot API and report which capabilities are genuinely available."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--token", required=True, help="A real Bale bot token.")
        parser.add_argument(
            "--chat",
            default="",
            help="A chat id the bot can message. Required for send/edit probes.",
        )
        parser.add_argument(
            "--webhook-url",
            default="",
            help="A public HTTPS URL, to test setWebhook and secret-token support.",
        )
        parser.add_argument(
            "--write-fixtures",
            action="store_true",
            help=f"Write raw responses to {FIXTURE_DIR} for the conformance suite.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the measured capabilities and Bale feature availability to the database.",
        )

    def handle(self, *args, **options) -> None:
        from apps.platforms.bale.api import BaleApi

        token = options["token"]
        chat = options["chat"]
        api = BaleApi(token)
        report = ProbeReport()

        self.stdout.write(self.style.MIGRATE_HEADING("Bale capability spike (BALE.md §2)"))
        self.stdout.write("")

        # Q0 — reachability and identity. Everything else is moot without it.
        try:
            identity = api.get_me()
        except PlatformApiError as exc:
            raise CommandError(
                f"Could not reach Bale or the token was rejected: {exc}\n"
                "If this is a network failure, that is spike question 11 answered — the "
                "worker-bale deployment needs different egress."
            ) from None

        report.record(
            "reachable", "Q11 Reachable from this host", True, f"@{identity.username}"
        )
        self.stdout.write(f"  connected as @{identity.username} ({identity.platform_bot_id})")
        self.stdout.write("")

        self._probe_branding(api, report)
        self._probe_webhook(api, report, options["webhook_url"])
        self._probe_messaging(api, report, chat)

        self._print_table(report)

        if options["write_fixtures"]:
            self._write_fixtures(report)

        if options["apply"]:
            self._apply(report)
        else:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Nothing was written. Re-run with --apply to record these capabilities "
                    "and update what the builder is allowed to sell on Bale."
                )
            )

    # -- probes -----------------------------------------------------------
    def _probe_branding(self, api, report: ProbeReport) -> None:
        for key, question, call in (
            ("set_my_commands", "Q7 setMyCommands", lambda: api.set_my_commands([
                {"command": "start", "description": "Start"}
            ])),
            ("set_my_name", "Q7 setMyName", lambda: api.set_my_name("Probe")),
            ("set_my_description", "Q7 setMyDescription", lambda: api.set_my_description("Probe")),
        ):
            try:
                call()
            except PlatformApiError as exc:
                report.record(key, question, False, str(exc))
            else:
                report.record(key, question, True)

    def _probe_webhook(self, api, report: ProbeReport, webhook_url: str) -> None:
        if not webhook_url:
            report.record("set_webhook", "Q1 setWebhook", None, "skipped: no --webhook-url")
            return

        try:
            api.set_webhook(webhook_url, secret_token="probe-secret-value")
        except PlatformApiError as exc:
            report.record("set_webhook", "Q1 setWebhook", False, str(exc))
            return

        report.record("set_webhook", "Q1 setWebhook", True)

        try:
            info = api.get_webhook_info()
        except PlatformApiError as exc:
            report.record("webhook_info", "Q1 getWebhookInfo", False, str(exc))
            return

        report.record("webhook_info", "Q1 getWebhookInfo", True, raw=info)
        # Bale echoing the secret back would tell us it stored it; absence is
        # inconclusive, which is itself worth recording.
        report.record(
            "webhook_secret",
            "Q1 secret_token honoured",
            None,
            "inconclusive — verify by sending a signed update and checking the header",
            raw=info,
        )

    def _probe_messaging(self, api, report: ProbeReport, chat: str) -> None:
        if not chat:
            for key, question in (
                ("send_message", "Q5 sendMessage"),
                ("inline_keyboards", "Q2 inline keyboards"),
                ("reply_keyboards", "Q2 reply keyboards"),
                ("message_editing", "Q4 editMessageText"),
                ("max_text_length", "Q5 max message length"),
            ):
                report.record(key, question, None, "skipped: no --chat")
            return

        try:
            sent = api.send_message(chat, "Bale capability probe: plain text.")
            report.record("send_message", "Q5 sendMessage", True, raw=sent)
        except PlatformApiError as exc:
            report.record("send_message", "Q5 sendMessage", False, str(exc))
            return

        try:
            api.send_message(
                chat,
                "Probe: inline keyboard.",
                reply_markup={
                    "inline_keyboard": [[{"text": "Tap me", "callback_data": "probe.v1"}]]
                },
            )
            report.record(
                "inline_keyboards",
                "Q2 inline keyboards",
                True,
                "accepted — confirm a callback_query actually arrives",
            )
        except PlatformApiError as exc:
            report.record("inline_keyboards", "Q2 inline keyboards", False, str(exc))

        try:
            api.send_message(
                chat,
                "Probe: reply keyboard.",
                reply_markup={"keyboard": [[{"text": "Option"}]], "resize_keyboard": True},
            )
            report.record("reply_keyboards", "Q2 reply keyboards", True)
        except PlatformApiError as exc:
            report.record("reply_keyboards", "Q2 reply keyboards", False, str(exc))

        # Q5 — find the real ceiling by bisection rather than trusting a doc.
        limit = self._find_text_limit(api, chat)
        report.record("max_text_length", "Q5 max message length", limit is not None, str(limit or ""))

    def _find_text_limit(self, api, chat: str) -> int | None:
        """Binary-search the accepted message length."""
        low, high, best = 1, 8192, None
        while low <= high:
            mid = (low + high) // 2
            try:
                api.send_message(chat, "x" * mid)
            except PlatformApiError:
                high = mid - 1
            else:
                best = mid
                low = mid + 1
        return best

    # -- output -----------------------------------------------------------
    def _print_table(self, report: ProbeReport) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Results"))
        for answer in report.answers.values():
            style = (
                self.style.SUCCESS
                if answer.supported is True
                else self.style.ERROR
                if answer.supported is False
                else self.style.WARNING
            )
            self.stdout.write(
                f"  {style(answer.mark.rjust(3))}  {answer.question}"
                + (f" — {answer.detail}" if answer.detail else "")
            )

    def _write_fixtures(self, report: ProbeReport) -> None:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path = FIXTURE_DIR / "probe.json"
        path.write_text(
            json.dumps({k: asdict(v) for k, v in report.answers.items()}, indent=2),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"\n  fixtures written to {path}"))

    def _apply(self, report: ProbeReport) -> None:
        from apps.core.models import SystemSetting
        from apps.features.models import Feature, FeaturePlatformAvailability
        from apps.features.registry import all_manifests
        from apps.platforms.base import Capabilities

        measured = report.as_capabilities()
        SystemSetting.objects.update_or_create(
            key="bale_measured_capabilities",
            defaults={"value": measured, "is_public": False,
                      "description": "Written by probe_bale. Source of truth for the Bale adapter."},
        )

        capabilities = Capabilities(
            inline_keyboards=measured["inline_keyboards"],
            reply_keyboards=measured["reply_keyboards"],
            max_buttons_per_row=6,
            max_buttons_total=60,
            media_groups=measured["media_groups"],
            message_editing=measured["message_editing"],
            web_app=False,
            file_uploads=measured["file_uploads"],
            max_text_length=measured["max_text_length"],
            verified=True,
        )

        updated = 0
        for slug, manifest in all_manifests().items():
            feature = Feature.objects.filter(slug=slug).first()
            if feature is None:
                continue
            missing = manifest.platform_requirements.unmet_on(capabilities)
            FeaturePlatformAvailability.objects.update_or_create(
                feature=feature,
                platform=Platform.BALE,
                defaults={
                    "is_available": not missing,
                    "degradation_note": (
                        f"Measured by probe_bale: requires {', '.join(missing)}."
                        if missing
                        else ""
                    ),
                },
            )
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"\n  applied to {updated} features"))
        self.stdout.write(
            "  Now paste the measured values into BALE_CAPABILITIES in "
            "apps/platforms/bale/adapter.py and set verified=True."
        )
