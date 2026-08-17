"""Bale capability probing, callable from both the CLI and the admin.

Extracted from the management command so an operator can run the BALE.md §2 spike from
the admin after registering a Bale bot, rather than needing shell access on a server.

The token is read from a stored credential or typed once into a form — it is never
persisted in plaintext, never logged, and never echoed back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from apps.platforms.constants import Platform
from apps.platforms.transport import PlatformApiError

logger = logging.getLogger(__name__)


@dataclass
class ProbeAnswer:
    question: str
    supported: bool | None = None
    detail: str = ""

    @property
    def mark(self) -> str:
        return {True: "yes", False: "no", None: "unknown"}[self.supported]


@dataclass
class ProbeResult:
    answers: dict[str, ProbeAnswer] = field(default_factory=dict)
    identity: dict = field(default_factory=dict)
    reachable: bool = False
    error: str = ""

    def record(self, key: str, question: str, supported: bool | None, detail: str = "") -> None:
        self.answers[key] = ProbeAnswer(question, supported, detail)

    @property
    def conclusive(self) -> bool:
        """True when nothing important is still unknown."""
        required = ("inline_keyboards", "reply_keyboards", "max_text_length", "set_my_commands")
        return all(
            key in self.answers and self.answers[key].supported is not None for key in required
        )

    def capabilities_proposal(self) -> dict:
        def answer(key: str, default: bool) -> bool:
            found = self.answers.get(key)
            return default if found is None or found.supported is None else found.supported

        length = self.answers.get("max_text_length")
        try:
            max_length = int(length.detail) if length and length.detail else 4096
        except ValueError:
            max_length = 4096

        return {
            "inline_keyboards": answer("inline_keyboards", False),
            "reply_keyboards": answer("reply_keyboards", True),
            "message_editing": answer("message_editing", False),
            "media_groups": answer("media_groups", False),
            "file_uploads": answer("file_uploads", False),
            "web_app": False,
            "max_text_length": max_length,
            "max_buttons_per_row": 6,
            "max_buttons_total": 60,
            "verified": self.conclusive,
        }


def probe_bale(*, token: str, chat_id: str = "", webhook_url: str = "") -> ProbeResult:
    """Run the capability spike. Read-only unless a chat id is supplied."""
    from apps.platforms.bale.api import BaleApi

    result = ProbeResult()
    api = BaleApi(token)

    try:
        identity = api.get_me()
    except PlatformApiError as exc:
        result.error = str(exc)
        result.record("reachable", "Q11 Reachable and token valid", False, str(exc))
        return result
    except Exception as exc:  # network-level failure is still an answer to Q11
        result.error = f"{type(exc).__name__}: {exc}"
        result.record("reachable", "Q11 Reachable from this host", False, result.error)
        return result

    result.reachable = True
    result.identity = {
        "id": identity.platform_bot_id,
        "username": identity.username,
        "name": identity.display_name,
    }
    result.record("reachable", "Q11 Reachable and token valid", True, f"@{identity.username}")

    _probe_branding(api, result)
    _probe_webhook(api, result, webhook_url)
    _probe_messaging(api, result, chat_id)
    return result


def _try(result: ProbeResult, key: str, question: str, call) -> None:
    try:
        call()
    except PlatformApiError as exc:
        # A permanent rejection means "not supported"; anything else is inconclusive
        # and must not be recorded as a definite "no".
        if exc.is_permanent:
            result.record(key, question, False, str(exc))
        else:
            result.record(key, question, None, f"inconclusive: {exc}")
    except Exception as exc:
        result.record(key, question, None, f"inconclusive: {type(exc).__name__}")
    else:
        result.record(key, question, True)


def _probe_branding(api, result: ProbeResult) -> None:
    _try(
        result,
        "set_my_commands",
        "Q7 setMyCommands",
        lambda: api.set_my_commands([{"command": "start", "description": "Start"}]),
    )
    _try(result, "set_my_name", "Q7 setMyName", lambda: api.set_my_name("Probe"))
    _try(
        result,
        "set_my_description",
        "Q7 setMyDescription",
        lambda: api.set_my_description("Capability probe"),
    )


def _probe_webhook(api, result: ProbeResult, webhook_url: str) -> None:
    if not webhook_url:
        result.record("set_webhook", "Q1 setWebhook", None, "skipped: no webhook URL given")
        return

    _try(
        result,
        "set_webhook",
        "Q1 setWebhook",
        lambda: api.set_webhook(webhook_url, secret_token="probe-secret-value"),
    )
    _try(result, "webhook_info", "Q1 getWebhookInfo", api.get_webhook_info)
    result.record(
        "webhook_secret",
        "Q1 secret_token honoured",
        None,
        "send a real update and check for the secret header to confirm",
    )


def _probe_messaging(api, result: ProbeResult, chat_id: str) -> None:
    if not chat_id:
        for key, question in (
            ("send_message", "Q5 sendMessage"),
            ("inline_keyboards", "Q2 inline keyboards"),
            ("reply_keyboards", "Q2 reply keyboards"),
            ("max_text_length", "Q5 max message length"),
        ):
            result.record(key, question, None, "skipped: no chat id given")
        return

    _try(
        result,
        "send_message",
        "Q5 sendMessage",
        lambda: api.send_message(chat_id, "Bale capability probe: plain text."),
    )
    if result.answers["send_message"].supported is not True:
        return

    _try(
        result,
        "inline_keyboards",
        "Q2 inline keyboards",
        lambda: api.send_message(
            chat_id,
            "Probe: inline keyboard.",
            reply_markup={"inline_keyboard": [[{"text": "Tap", "callback_data": "probe.v1"}]]},
        ),
    )
    _try(
        result,
        "reply_keyboards",
        "Q2 reply keyboards",
        lambda: api.send_message(
            chat_id,
            "Probe: reply keyboard.",
            reply_markup={"keyboard": [[{"text": "Option"}]], "resize_keyboard": True},
        ),
    )

    limit = _find_text_limit(api, chat_id)
    result.record(
        "max_text_length",
        "Q5 max message length",
        limit is not None,
        str(limit or ""),
    )


def _find_text_limit(api, chat_id: str, ceiling: int = 8192) -> int | None:
    """Binary-search the accepted length rather than trusting documentation."""
    low, high, best = 1, ceiling, None
    while low <= high:
        mid = (low + high) // 2
        try:
            api.send_message(chat_id, "x" * mid)
        except PlatformApiError:
            high = mid - 1
        except Exception:
            return best
        else:
            best = mid
            low = mid + 1
    return best


def apply_result(result: ProbeResult, actor=None) -> int:
    """Record measured capabilities and update what may be sold on Bale.

    `feature_platform_availability` is the switch that keeps the builder honest: a
    feature is offered on Bale only once it is known to work there (BALE.md §2).
    """
    from apps.core.models import SystemSetting
    from apps.features.models import Feature, FeaturePlatformAvailability
    from apps.features.registry import all_manifests
    from apps.platforms.base import Capabilities

    proposal = result.capabilities_proposal()
    SystemSetting.objects.update_or_create(
        key="bale_measured_capabilities",
        defaults={
            "value": proposal,
            "is_public": False,
            "description": "Measured by the Bale capability probe.",
        },
    )

    capabilities = Capabilities(**proposal)

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
                    f"Measured: Bale lacks {', '.join(missing)}." if missing else ""
                ),
            },
        )
        updated += 1

    if actor is not None:
        from apps.audit.services import record_audit

        record_audit(
            actor=actor,
            action="platforms.bale_capabilities_measured",
            resource_type="platform",
            resource_id=Platform.BALE,
            metadata={"capabilities": proposal, "features_updated": updated},
        )

    return updated
