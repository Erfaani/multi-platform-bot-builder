from __future__ import annotations

import pytest

from apps.accounts.models import StaffRole, User, UserStaffRole
from apps.accounts.services import has_scope
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"


class TestRegistration:
    def test_creates_an_account_and_returns_tokens(self, api):
        response = api.post(
            REGISTER,
            {"email": "New@Example.com", "password": "Str0ng-Passphrase!"},
            format="json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["access"] and body["refresh"]
        # Email is normalised to lowercase so it cannot be registered twice by case.
        assert body["user"]["email"] == "new@example.com"

    def test_duplicate_email_is_rejected(self, api, user):
        response = api.post(
            REGISTER, {"email": user.email, "password": "Str0ng-Passphrase!"}, format="json"
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "accounts.email_taken"

    def test_short_password_is_rejected(self, api):
        response = api.post(REGISTER, {"email": "a@example.com", "password": "short"}, format="json")
        assert response.status_code == 400
        assert "password" in response.json()["error"]["field_errors"]

    def test_common_password_is_rejected(self, api):
        response = api.post(
            REGISTER, {"email": "a@example.com", "password": "password1234"}, format="json"
        )
        assert response.status_code == 400

    def test_registration_is_audited(self, api):
        api.post(
            REGISTER, {"email": "audit@example.com", "password": "Str0ng-Passphrase!"}, format="json"
        )
        assert AuditLog.objects.filter(action="user.registered").exists()

    def test_new_account_is_not_email_verified(self, api):
        response = api.post(
            REGISTER, {"email": "v@example.com", "password": "Str0ng-Passphrase!"}, format="json"
        )
        assert response.json()["user"]["is_email_verified"] is False


class TestLogin:
    def test_valid_credentials_return_tokens(self, api, user):
        response = api.post(LOGIN, {"email": user.email, "password": "TestPassw0rd!23"}, format="json")
        assert response.status_code == 200
        assert response.json()["access"]

    def test_wrong_password_is_generic(self, api, user):
        response = api.post(LOGIN, {"email": user.email, "password": "wrong-password"}, format="json")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "accounts.invalid_credentials"

    def test_unknown_email_is_indistinguishable_from_wrong_password(self, api, user):
        """Otherwise login becomes an account-enumeration oracle."""
        unknown = api.post(
            LOGIN, {"email": "nobody@example.com", "password": "whatever-1234"}, format="json"
        )
        wrong = api.post(LOGIN, {"email": user.email, "password": "whatever-1234"}, format="json")
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]
        assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    def test_inactive_account_cannot_log_in(self, api, user):
        user.is_active = False
        user.save(update_fields=["is_active"])
        assert api.post(
            LOGIN, {"email": user.email, "password": "TestPassw0rd!23"}, format="json"
        ).status_code == 401

    def test_failed_login_is_audited_without_the_password(self, api, user):
        api.post(LOGIN, {"email": user.email, "password": "wrong-password"}, format="json")
        entry = AuditLog.objects.filter(action="user.login_failed").first()
        assert entry is not None
        assert "wrong-password" not in str(entry.metadata)


class TestTokens:
    def test_refresh_returns_a_new_access_token(self, api, user):
        tokens = api.post(
            LOGIN, {"email": user.email, "password": "TestPassw0rd!23"}, format="json"
        ).json()
        response = api.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        assert response.status_code == 200
        assert response.json()["access"]

    def test_rotated_refresh_token_cannot_be_replayed(self, api, user):
        """Replay of a rotated token is how a stolen refresh token surfaces."""
        tokens = api.post(
            LOGIN, {"email": user.email, "password": "TestPassw0rd!23"}, format="json"
        ).json()
        first = api.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        assert first.status_code == 200

        replay = api.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        assert replay.status_code == 401

    def test_garbage_refresh_token_is_rejected(self, api):
        response = api.post("/api/v1/auth/refresh/", {"refresh": "not-a-token"}, format="json")
        assert response.status_code == 401


class TestProfile:
    def test_me_requires_authentication(self, api):
        assert api.get(ME).status_code == 401

    def test_me_returns_the_current_user(self, auth_client, user):
        assert auth_client.get(ME).json()["email"] == user.email

    def test_locale_preference_can_be_updated(self, auth_client):
        response = auth_client.patch(ME, {"preferred_locale": "fa"}, format="json")
        assert response.status_code == 200
        assert response.json()["preferred_locale"] == "fa"

    def test_unsupported_locale_is_rejected(self, auth_client):
        response = auth_client.patch(ME, {"preferred_locale": "kl"}, format="json")
        assert response.status_code == 400

    def test_email_is_read_only(self, auth_client, user):
        auth_client.patch(ME, {"email": "hijack@example.com"}, format="json")
        user.refresh_from_db()
        assert user.email != "hijack@example.com"


class TestStaffScopes:
    def test_superuser_has_every_scope(self, superadmin):
        assert has_scope(superadmin, "anything.at.all")

    def test_support_agent_cannot_approve_payments(self, db):
        agent = User.objects.create_user(email="support@example.com", password="TestPassw0rd!23")
        UserStaffRole.objects.create(user=agent, role=StaffRole.SUPPORT_AGENT)
        assert has_scope(agent, "support.manage")
        assert not has_scope(agent, "payments.review")

    def test_finance_agent_cannot_suspend_bots(self, db):
        agent = User.objects.create_user(email="finance@example.com", password="TestPassw0rd!23")
        UserStaffRole.objects.create(user=agent, role=StaffRole.FINANCE_AGENT)
        assert has_scope(agent, "payments.review")
        assert not has_scope(agent, "bots.manage")

    def test_ordinary_user_has_no_staff_scopes(self, user):
        assert not has_scope(user, "dashboard.view")
