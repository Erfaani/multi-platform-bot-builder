"""Seed reference and demo data.

Idempotent: safe to run repeatedly against the same database. Reference data
(currencies, system settings) is always seeded; demo tenants only with --demo.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import StaffRole, User, UserStaffRole
from apps.core.formatting import invalidate_currency_cache
from apps.core.models import Currency, SystemSetting
from apps.customers.models import Tenant, TenantMembership, TenantRole

CURRENCIES = [
    # code, name, symbol, exponent, display_unit, divisor, sort
    ("USD", "US Dollar", "$", 2, "", 1, 10),
    ("EUR", "Euro", "€", 2, "", 1, 20),
    # IRR is the currency; Toman is its display unit (÷10). See ADR-0004.
    ("IRR", "Iranian Rial", "﷼", 0, "TOMAN", 10, 30),
    ("USDT", "Tether", "", 6, "", 1, 40),
]

SETTINGS = [
    ("brand_name", "Bot Builder Platform", True, "Public brand name."),
    ("support_email", "support@example.com", True, "Shown to customers."),
    ("support_telegram", "", True, "Optional support handle."),
    ("default_locale", "en", True, "Fallback locale."),
    ("terms_url", "", True, "Link to terms of service."),
    ("privacy_url", "", True, "Link to the privacy policy."),
    # "pool" is the Instant tier and the headline product story: zero-touch, live in
    # seconds. Orders that need a vanity @username set "token_handoff" explicitly.
    ("provisioning_default_strategy", "pool", False, "ADR-0002 tier: pool | token_handoff."),
]


class Command(BaseCommand):
    help = "Seed reference data, and optionally a demo tenant."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--demo", action="store_true", help="Also create demo accounts.")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        self._seed_currencies()
        self._seed_settings()
        if options["demo"]:
            self._seed_demo()
        invalidate_currency_cache()
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _seed_currencies(self) -> None:
        for code, name, symbol, exponent, unit, divisor, order in CURRENCIES:
            Currency.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "symbol": symbol,
                    "exponent": exponent,
                    "display_unit": unit,
                    "display_divisor": divisor,
                    "sort_order": order,
                    "is_active": True,
                },
            )
        self.stdout.write(f"  currencies: {len(CURRENCIES)}")

    def _seed_settings(self) -> None:
        for key, value, is_public, description in SETTINGS:
            SystemSetting.objects.update_or_create(
                key=key,
                defaults={"value": value, "is_public": is_public, "description": description},
            )
        self.stdout.write(f"  settings: {len(SETTINGS)}")

    def _seed_demo(self) -> None:
        admin, created = User.objects.get_or_create(
            email="admin@example.com",
            defaults={
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Platform",
                "last_name": "Admin",
                "email_verified_at": timezone.now(),
            },
        )
        if created:
            admin.set_password("ChangeMe!2026")
            admin.save()
        UserStaffRole.objects.get_or_create(user=admin, role=StaffRole.SUPER_ADMIN)

        owner, created = User.objects.get_or_create(
            email="owner@example.com",
            defaults={
                "first_name": "Demo",
                "last_name": "Owner",
                "preferred_locale": "fa",
                "preferred_currency": "IRR",
                "country": "IR",
                "timezone": "Asia/Tehran",
                "email_verified_at": timezone.now(),
            },
        )
        if created:
            owner.set_password("ChangeMe!2026")
            owner.save()

        tenant, _ = Tenant.objects.get_or_create(
            slug="demo-clinic",
            defaults={
                "name": "Demo Clinic",
                "country": "IR",
                "default_locale": "fa",
                "default_currency": "IRR",
                "timezone": "Asia/Tehran",
                "created_by": owner,
            },
        )
        TenantMembership.objects.get_or_create(
            tenant=tenant,
            user=owner,
            defaults={"role": TenantRole.OWNER, "accepted_at": timezone.now()},
        )

        self.stdout.write("  demo: admin@example.com / owner@example.com (password ChangeMe!2026)")
        self.stdout.write(
            self.style.WARNING("  Demo passwords are for local development only.")
        )
