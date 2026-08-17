"""Operator screens (Django admin).

These pages are how someone without shell access registers a bot and closes the Bale
capability gap, so they need to actually load — a 500 here means the spike cannot be run
by the person holding the token.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import StaffRole, User, UserStaffRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client_(client, db):
    user = User.objects.create_superuser(email="ops@example.com", password="TestPassw0rd!23")
    UserStaffRole.objects.create(user=user, role=StaffRole.SUPER_ADMIN)
    client.force_login(user)
    return client


class TestPlatformConsole:
    def test_the_console_loads(self, admin_client_):
        response = admin_client_.get(reverse("admin:bots_platform_console"))
        assert response.status_code == 200

    def test_it_reports_both_channels(self, admin_client_):
        body = admin_client_.get(reverse("admin:bots_platform_console")).content.decode()
        assert "telegram" in body
        assert "bale" in body

    def test_it_says_bale_is_provisional(self, admin_client_):
        """An operator must be able to see, at a glance, that Bale is unverified."""
        body = admin_client_.get(reverse("admin:bots_platform_console")).content.decode()
        assert "provisional" in body.lower()

    def test_it_requires_staff(self, client):
        response = client.get(reverse("admin:bots_platform_console"))
        assert response.status_code in (302, 403)


class TestRegisterBot:
    def test_the_form_loads(self, admin_client_):
        response = admin_client_.get(reverse("admin:bots_pool_add"))
        assert response.status_code == 200
        assert "username" in response.content.decode()

    def test_registering_a_bale_bot_stocks_the_pool(self, admin_client_, fake_transport):
        from apps.bots.models import BotPoolEntry

        response = admin_client_.post(
            reverse("admin:bots_pool_add"),
            {
                "platform": "bale",
                "username": "my_bale_test_bot",
                "token": "7300000001:AA-a-real-looking-bale-token-zzzz",
                "note": "dev bot",
            },
        )
        assert response.status_code in (200, 302)

        entry = BotPoolEntry.objects.get(username="my_bale_test_bot")
        assert entry.platform == "bale"
        assert entry.status == BotPoolEntry.Status.AVAILABLE

    def test_the_token_is_never_stored_in_plaintext(self, admin_client_, fake_transport):
        from apps.bots.models import BotPoolEntry

        token = "7300000002:AA-secret-bale-token-qqqqqqqqqqqq"
        admin_client_.post(
            reverse("admin:bots_pool_add"),
            {"platform": "bale", "username": "secret_bot", "token": token, "note": ""},
        )
        entry = BotPoolEntry.objects.get(username="secret_bot")
        assert token.encode() not in bytes(entry.ciphertext)

    def test_a_duplicate_token_is_rejected(self, admin_client_, fake_transport):
        token = "7300000003:AA-duplicate-bale-token-wwwwwwww"
        for username in ("first_bot", "second_bot"):
            admin_client_.post(
                reverse("admin:bots_pool_add"),
                {"platform": "bale", "username": username, "token": token, "note": ""},
            )

        from apps.bots.models import BotPoolEntry

        assert BotPoolEntry.objects.filter(fingerprint__isnull=False).count() >= 1
        assert not BotPoolEntry.objects.filter(username="second_bot").exists()


class TestBaleProbeScreen:
    def test_the_probe_form_loads(self, admin_client_):
        response = admin_client_.get(reverse("admin:bots_probe_bale"))
        assert response.status_code == 200
        assert "token" in response.content.decode().lower()

    def test_an_unreachable_platform_reports_rather_than_crashing(
        self, admin_client_, fake_transport
    ):
        """A network failure is spike question 11 answered, not a 500."""
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["getMe"] = PlatformApiError(
            "Unauthorized", status_code=401, method="getMe"
        )
        response = admin_client_.post(
            reverse("admin:bots_probe_bale"),
            {"token": "7400000001:AA-bad-token-eeeeeeeeeeeeeeeee", "chat_id": "", "webhook_url": ""},
        )
        assert response.status_code == 200
        assert "not reachable" in response.content.decode().lower()

    def test_a_successful_probe_reports_answers(self, admin_client_, fake_transport):
        response = admin_client_.post(
            reverse("admin:bots_probe_bale"),
            {
                "token": "7400000002:AA-good-token-rrrrrrrrrrrrrrrr",
                "chat_id": "",
                "webhook_url": "",
            },
        )
        body = response.content.decode()
        assert response.status_code == 200
        assert "Q7 setMyCommands" in body

    def test_applying_results_updates_bale_availability(
        self, admin_client_, catalogue, fake_transport
    ):
        from apps.features.models import FeaturePlatformAvailability

        admin_client_.post(
            reverse("admin:bots_probe_bale"),
            {
                "token": "7400000003:AA-apply-token-tttttttttttttt",
                "chat_id": "",
                "webhook_url": "",
                "apply_results": "on",
            },
        )
        assert FeaturePlatformAvailability.objects.filter(platform="bale").exists()
