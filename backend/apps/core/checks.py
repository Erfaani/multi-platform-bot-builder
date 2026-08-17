"""Startup configuration checks.

A misconfigured encryption key must surface at `runserver`/deploy time, not the first
time a customer submits a bot token. The placeholder in `.env.example` deliberately
cannot decode, so this check is what turns that into a clear message.
"""

from __future__ import annotations

from django.core.checks import Error, Warning, register

CORE_TAG = "core"


@register(CORE_TAG)
def check_encryption_key(app_configs, **kwargs) -> list:
    from django.conf import settings

    from apps.core.encryption import DEK_BYTES

    problems: list = []
    raw = getattr(settings, "ENCRYPTION_KEK", "")

    if not raw:
        problems.append(
            Error(
                "ENCRYPTION_KEK is not set. Bot credentials cannot be stored without it.",
                hint=(
                    "Generate one with:\n"
                    "  python -c \"import base64,os;"
                    'print(base64.b64encode(os.urandom(32)).decode())"'
                ),
                id="core.E001",
            )
        )
        return problems

    import base64
    import binascii

    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        problems.append(
            Error(
                "ENCRYPTION_KEK is not valid base64 — the placeholder value is still in "
                "place.",
                hint=(
                    "Generate a real key:\n"
                    "  python -c \"import base64,os;"
                    'print(base64.b64encode(os.urandom(32)).decode())"'
                ),
                id="core.E002",
            )
        )
        return problems

    if len(key) != DEK_BYTES:
        problems.append(
            Error(
                f"ENCRYPTION_KEK decodes to {len(key)} bytes; {DEK_BYTES} are required.",
                id="core.E003",
            )
        )

    previous = getattr(settings, "ENCRYPTION_KEK_PREVIOUS", "") or ""
    for entry in filter(None, (part.strip() for part in previous.split(","))):
        if ":" not in entry:
            problems.append(
                Warning(
                    "ENCRYPTION_KEK_PREVIOUS entries must be `version:base64key`; "
                    f"ignoring {entry[:12]}…",
                    hint="Ciphertext written under a retired key will fail to decrypt.",
                    id="core.W001",
                )
            )

    return problems
