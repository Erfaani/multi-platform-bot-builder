"""Payment provider abstraction (spec §16).

MVP is manual, but the order system talks to this interface rather than to "card
transfer", so adding Stripe or an Iranian gateway later is a new provider class and a
`PaymentMethod` row — not a rewrite of checkout.

    PaymentProvider
        ├── ManualCardProvider
        ├── ManualCryptoProvider
        └── (future) GatewayProvider
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from django.utils.translation import gettext_lazy as _

from apps.core.errors import ValidationError


@dataclass(frozen=True, slots=True)
class PaymentInstructions:
    """What the customer must be shown in order to pay."""

    headline: str
    fields: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Value the UI should offer a one-tap copy button for (card number, wallet address).
    copyable: str = ""


@dataclass(frozen=True, slots=True)
class ProofRequirements:
    """What the customer must supply as proof."""

    requires_file: bool = True
    requires_tx_hash: bool = False
    optional_fields: tuple[str, ...] = ()


class PaymentProvider(Protocol):
    slug: str
    kind: str

    def instructions(self, *, method, payment) -> PaymentInstructions: ...
    def proof_requirements(self, *, method) -> ProofRequirements: ...
    def validate_proof(self, *, method, data: dict) -> dict: ...
    def is_automatic(self) -> bool: ...


class ManualProviderBase:
    """Shared behaviour for providers a human verifies."""

    slug = "manual"
    kind = "MANUAL"

    def is_automatic(self) -> bool:
        return False

    def validate_proof(self, *, method, data: dict) -> dict:
        return data


class ManualCardProvider(ManualProviderBase):
    """Iranian card-to-card transfer (spec §14)."""

    slug = "manual_card"
    kind = "MANUAL_CARD"

    def instructions(self, *, method, payment) -> PaymentInstructions:
        config = method.config or {}
        return PaymentInstructions(
            headline=str(_("Transfer the amount to the card below, then upload your receipt.")),
            fields=[
                {"label": str(_("Card number")), "value": config.get("card_number", ""), "copyable": True},
                {"label": str(_("Card holder")), "value": config.get("card_holder", "")},
                {"label": str(_("Bank")), "value": config.get("bank_name", "")},
            ],
            notes=[method.instructions] if method.instructions else [],
            copyable=config.get("card_number", ""),
        )

    def proof_requirements(self, *, method) -> ProofRequirements:
        return ProofRequirements(requires_file=True, requires_tx_hash=False)


class ManualCryptoProvider(ManualProviderBase):
    """Manually verified cryptocurrency transfer (spec §15).

    Automatic on-chain verification is deliberately out of scope for the MVP; the
    architecture supports adding it as a different provider later.
    """

    slug = "manual_crypto"
    kind = "MANUAL_CRYPTO"

    def instructions(self, *, method, payment) -> PaymentInstructions:
        config = method.config or {}
        address = config.get("wallet_address", "")
        return PaymentInstructions(
            headline=str(_("Send the exact amount to the address below, then submit your proof.")),
            fields=[
                {"label": str(_("Currency")), "value": method.currency},
                {"label": str(_("Network")), "value": method.network},
                {"label": str(_("Wallet address")), "value": address, "copyable": True},
            ],
            notes=[
                *( [method.instructions] if method.instructions else [] ),
                str(_("Send on the stated network only. Funds sent on another network are unrecoverable.")),
            ],
            copyable=address,
        )

    def proof_requirements(self, *, method) -> ProofRequirements:
        # The transaction hash is the real evidence here; a screenshot is trivially
        # faked and cannot be checked on-chain later.
        return ProofRequirements(
            requires_file=False,
            requires_tx_hash=True,
            optional_fields=("sender_wallet", "screenshot"),
        )

    def validate_proof(self, *, method, data: dict) -> dict:
        tx_hash = (data.get("tx_hash") or "").strip()
        if not tx_hash:
            raise ValidationError(
                code="payment.tx_hash_required",
                field_errors={"tx_hash": [str(_("A transaction hash is required."))]},
            )
        if len(tx_hash) < 16:
            raise ValidationError(
                code="payment.tx_hash_invalid",
                field_errors={"tx_hash": [str(_("That does not look like a transaction hash."))]},
            )
        data["tx_hash"] = tx_hash
        return data


_REGISTRY: dict[str, PaymentProvider] = {}


def register(provider: PaymentProvider) -> None:
    _REGISTRY[provider.slug] = provider


def get_provider(slug: str) -> PaymentProvider:
    try:
        return _REGISTRY[slug]
    except KeyError as exc:
        raise LookupError(f"No payment provider registered for {slug!r}.") from exc


def provider_for(method) -> PaymentProvider:
    return get_provider(method.provider_slug)


register(ManualCardProvider())
register(ManualCryptoProvider())
