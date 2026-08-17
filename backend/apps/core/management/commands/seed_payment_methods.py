"""Seed manual payment methods (spec §14, §15).

Placeholder receiving details only. Real card numbers and wallet addresses are entered
by an admin in the admin panel and are never committed to the repository (spec §15:
"Do not hard-code wallet addresses").
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.payments.models import PaymentMethod, PaymentMethodKind

PLACEHOLDER_CARD = "0000-0000-0000-0000"
PLACEHOLDER_WALLET = "SET-THIS-IN-THE-ADMIN"

METHODS = [
    {
        "name": "Card transfer (Iran)",
        "kind": PaymentMethodKind.MANUAL_CARD,
        "provider_slug": "manual_card",
        "currency": "IRR",
        "network": "",
        "country_scope": ["IR"],
        "sort_order": 10,
        "config": {
            "card_number": PLACEHOLDER_CARD,
            "card_holder": "Set the account holder in the admin",
            "bank_name": "Set the bank in the admin",
        },
        "instructions": (
            "Transfer the exact amount from any Iranian bank card, then upload a clear "
            "photo or screenshot of the receipt."
        ),
    },
    {
        "name": "USDT — TRC20",
        "kind": PaymentMethodKind.MANUAL_CRYPTO,
        "provider_slug": "manual_crypto",
        "currency": "USDT",
        "network": "TRC20",
        "country_scope": [],
        "sort_order": 20,
        "config": {"wallet_address": PLACEHOLDER_WALLET},
        "instructions": "TRON network only.",
    },
    {
        "name": "USDT — ERC20",
        "kind": PaymentMethodKind.MANUAL_CRYPTO,
        "provider_slug": "manual_crypto",
        "currency": "USDT",
        "network": "ERC20",
        "country_scope": [],
        "sort_order": 30,
        "config": {"wallet_address": PLACEHOLDER_WALLET},
        "instructions": "Ethereum network only. Gas fees are paid by the sender.",
    },
]


class Command(BaseCommand):
    help = "Seed manual payment methods with placeholder receiving details."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for spec in METHODS:
            method, created = PaymentMethod.objects.get_or_create(
                name=spec["name"],
                defaults={**spec, "is_enabled": False},
            )
            state = "created" if created else "exists"
            self.stdout.write(f"  {spec['name']}: {state}")

        self.stdout.write(
            self.style.WARNING(
                "\n  Seeded methods are DISABLED and hold placeholder details.\n"
                "  Set the real card number / wallet addresses in the admin, then enable\n"
                "  each method. Real payment details must never be committed."
            )
        )
