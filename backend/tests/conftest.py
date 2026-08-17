from __future__ import annotations

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import StaffRole, User, UserStaffRole
from apps.core.models import Currency
from apps.customers.models import Tenant, TenantMembership, TenantRole

# Phase 4 fixtures (fake transport, pool stock, provisioned bots).
from tests.conftest_bots import (  # noqa: F401
    active_instance,
    fake_transport,
    paid_order,
    pool_entry,
    provisioned_bot,
)


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture(scope="session")
def catalogue(django_db_setup, django_db_blocker):
    """Seed currencies and the full catalogue once for the whole session.

    Committed outside the per-test transaction, so every test sees it and no test can
    corrupt it for the next — their own changes roll back.
    """
    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("seed_demo", verbosity=0)
        call_command("seed_catalogue", verbosity=0)

    from apps.core.formatting import invalidate_currency_cache

    invalidate_currency_cache()


@pytest.fixture
def usd_price_list(catalogue, db):
    from apps.pricing.models import PriceList

    return PriceList.objects.get(slug="usd-international")


@pytest.fixture
def irr_price_list(catalogue, db):
    from apps.pricing.models import PriceList

    return PriceList.objects.get(slug="irr-iran")


@pytest.fixture
def currencies(db) -> None:
    Currency.objects.update_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "exponent": 2, "display_divisor": 1},
    )
    Currency.objects.update_or_create(
        code="IRR",
        defaults={
            "name": "Iranian Rial",
            "symbol": "﷼",
            "exponent": 0,
            "display_unit": "TOMAN",
            "display_divisor": 10,
        },
    )
    Currency.objects.update_or_create(
        code="USDT",
        defaults={"name": "Tether", "symbol": "", "exponent": 6, "display_divisor": 1},
    )
    from apps.core.formatting import invalidate_currency_cache

    invalidate_currency_cache()


def make_user(email: str, **extra) -> User:
    user = User.objects.create_user(
        email=email, password="TestPassw0rd!23", email_verified_at=timezone.now(), **extra
    )
    return user


@pytest.fixture
def user(db) -> User:
    return make_user("user@example.com")


@pytest.fixture
def other_user(db) -> User:
    return make_user("other@example.com")


@pytest.fixture
def superadmin(db) -> User:
    user = User.objects.create_superuser(email="root@example.com", password="TestPassw0rd!23")
    UserStaffRole.objects.create(user=user, role=StaffRole.SUPER_ADMIN)
    return user


def make_tenant(name: str, owner: User) -> Tenant:
    tenant = Tenant.objects.create(
        name=name, slug=name.lower().replace(" ", "-"), created_by=owner
    )
    TenantMembership.objects.create(
        tenant=tenant, user=owner, role=TenantRole.OWNER, accepted_at=timezone.now()
    )
    return tenant


@pytest.fixture
def tenant_a(db, user) -> Tenant:
    return make_tenant("Tenant A", user)


@pytest.fixture
def tenant_b(db, other_user) -> Tenant:
    return make_tenant("Tenant B", other_user)


@pytest.fixture
def auth_client(api, user) -> APIClient:
    from apps.accounts.services import issue_tokens

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user)['access']}")
    return api


@pytest.fixture
def other_client(other_user) -> APIClient:
    from apps.accounts.services import issue_tokens

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(other_user)['access']}")
    return client
