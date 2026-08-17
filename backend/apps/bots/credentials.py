"""Bot credential custody.

The only module permitted to decrypt a bot token. Everything else asks for a
transport that has already been bound to a credential, so plaintext tokens never
travel through business logic.

Rules enforced here:
- A token is encrypted before it is ever written.
- The same token cannot be registered to two instances (fingerprint uniqueness).
- Decryption is audit-logged with the caller's purpose.
- Plaintext is never returned to a caller outside this module's helpers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.audit.services import record_audit
from apps.core.encryption import decrypt, encrypt, fingerprint
from apps.core.errors import ConflictError, ValidationError
from apps.bots.models import BotCredential, BotPlatformInstance, BotPoolEntry

logger = logging.getLogger(__name__)

#: Telegram tokens look like `<numeric id>:<35+ url-safe chars>`. Bale's are similar.
MIN_TOKEN_LENGTH = 20


class CredentialError(Exception):
    """Raised when a credential cannot be stored or read."""


@dataclass(frozen=True, slots=True)
class TokenIdentity:
    """What a platform told us about a token when we validated it."""

    platform_bot_id: str
    username: str
    display_name: str


def _associated_data(instance: BotPlatformInstance) -> bytes:
    """Bind ciphertext to its instance.

    A credential row copied to another instance fails to decrypt, so a database-level
    mix-up cannot silently hand one customer another's bot.
    """
    return f"instance:{instance.public_id}".encode()


def validate_token_shape(token: str) -> str:
    token = (token or "").strip()
    if len(token) < MIN_TOKEN_LENGTH or ":" not in token:
        raise ValidationError(
            code="bots.invalid_token",
            field_errors={"token": ["That does not look like a bot token."]},
        )
    return token


@transaction.atomic
def store_token(*, instance: BotPlatformInstance, token: str, actor=None) -> BotCredential:
    """Encrypt and store a token against an instance."""
    token = validate_token_shape(token)
    digest = fingerprint(token)

    clash = (
        BotCredential.objects.filter(fingerprint=digest)
        .exclude(instance=instance)
        .exists()
        or BotPoolEntry.objects.filter(fingerprint=digest)
        .exclude(assigned_instance=instance)
        .exists()
    )
    if clash:
        # Without this, two customers could point at one bot and each would see the
        # other's conversations.
        raise ConflictError(
            code="bots.token_already_registered",
            message="That bot is already connected to another workspace.",
        )

    credential, _ = BotCredential.objects.update_or_create(
        instance=instance,
        defaults={
            "ciphertext": encrypt(token, associated_data=_associated_data(instance)),
            "fingerprint": digest,
        },
    )

    record_audit(
        actor=actor,
        action="bot.credential_stored",
        resource_type="bot_platform_instance",
        resource_id=str(instance.public_id),
        tenant=instance.bot.tenant,
        metadata={"platform": instance.platform},
    )
    return credential


def read_token(*, instance: BotPlatformInstance, purpose: str) -> str:
    """Decrypt a token for immediate use.

    `purpose` is recorded, so every decryption is attributable. Callers must not store
    or pass on the return value — bind it to a transport and let it go out of scope.
    """
    credential = getattr(instance, "credential", None)
    if credential is None:
        raise CredentialError(f"Instance {instance.public_id} has no credential.")

    try:
        token = decrypt(bytes(credential.ciphertext), associated_data=_associated_data(instance))
    except Exception as exc:
        raise CredentialError(
            f"Could not decrypt the credential for instance {instance.public_id}."
        ) from exc

    logger.info(
        "Decrypted credential for instance %s (purpose=%s)", instance.public_id, purpose
    )
    return token


def read_pool_token(entry: BotPoolEntry) -> str:
    """Pool entries are encrypted without instance binding — they have no instance yet."""
    try:
        return decrypt(bytes(entry.ciphertext))
    except Exception as exc:
        raise CredentialError(f"Could not decrypt pool entry {entry.public_id}.") from exc


@transaction.atomic
def add_pool_entry(
    *, platform: str, username: str, token: str, note: str = "", actor=None
) -> BotPoolEntry:
    """Stock the pool with a pre-created bot."""
    token = validate_token_shape(token)
    digest = fingerprint(token)

    if BotPoolEntry.objects.filter(fingerprint=digest).exists():
        raise ConflictError(
            code="bots.pool_token_duplicate", message="That token is already in the pool."
        )
    if BotCredential.objects.filter(fingerprint=digest).exists():
        raise ConflictError(
            code="bots.token_already_registered",
            message="That token is already assigned to a bot.",
        )

    entry = BotPoolEntry.objects.create(
        platform=platform,
        username=username.lstrip("@"),
        ciphertext=encrypt(token),
        fingerprint=digest,
        note=note,
        status=BotPoolEntry.Status.AVAILABLE,
    )
    record_audit(
        actor=actor,
        action="bot_pool.entry_added",
        resource_type="bot_pool_entry",
        resource_id=str(entry.public_id),
        metadata={"platform": platform, "username": entry.username},
    )
    return entry


def transfer_pool_credential(*, entry: BotPoolEntry, instance: BotPlatformInstance) -> BotCredential:
    """Move a pool entry's token onto an instance, re-binding it to that instance."""
    token = read_pool_token(entry)
    return store_token(instance=instance, token=token)


def pool_depth(platform: str) -> int:
    return BotPoolEntry.objects.filter(
        platform=platform, status=BotPoolEntry.Status.AVAILABLE
    ).count()
