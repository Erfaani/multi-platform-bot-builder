"""The public builder API — the Phase 2 exit criterion.

A visitor configures a bot, gets a server-computed itemised price, and previews it,
all without an account.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

QUOTES = "/api/v1/quotes/"


def create_quote(api, **overrides):
    payload = {
        "template": "clinic",
        "platforms": ["telegram"],
        "features": ["faq"],
        "currency": "USD",
    }
    payload.update(overrides)
    return api.post(QUOTES, payload, format="json")


class TestPublicCatalogue:
    def test_templates_are_public(self, api, catalogue):
        response = api.get("/api/v1/templates/")
        assert response.status_code == 200
        assert {row["slug"] for row in response.json()} >= {"clinic", "restaurant", "shop"}

    def test_templates_expose_their_defaults(self, api, catalogue):
        clinic = api.get("/api/v1/templates/clinic/").json()
        assert "appointment" in clinic["default_features"]
        assert "business_profile" in clinic["required_features"]

    def test_features_are_public(self, api, catalogue):
        response = api.get("/api/v1/features/")
        assert response.status_code == 200
        assert len(response.json()) >= 20

    def test_features_report_per_platform_availability(self, api, catalogue):
        rows = {row["slug"]: row for row in api.get("/api/v1/features/").json()}
        food = rows["food_ordering"]
        assert food["platforms"]["telegram"]["available"] is True
        assert food["platforms"]["bale"]["available"] is False

    def test_catalogue_is_localised(self, api, catalogue):
        english = api.get("/api/v1/templates/clinic/").json()["name"]
        persian = api.get("/api/v1/templates/clinic/?lang=fa").json()["name"]
        assert english == "Medical clinic"
        assert persian == "کلینیک پزشکی"

    def test_platforms_are_listed_with_verification_status(self, api, catalogue):
        rows = {row["slug"]: row for row in api.get("/api/v1/platforms/").json()}
        assert rows["telegram"]["capabilities_verified"] is True
        assert rows["bale"]["capabilities_verified"] is False

    def test_preview_is_not_offered_as_a_platform(self, api, catalogue):
        slugs = {row["slug"] for row in api.get("/api/v1/platforms/").json()}
        assert "preview" not in slugs


class TestQuoteEndpoint:
    def test_a_visitor_can_price_a_bot_without_an_account(self, api, catalogue):
        response = create_quote(api)
        assert response.status_code == 201

        body = response.json()
        assert body["total"]["amount_minor"] > 0
        assert body["items"]
        assert body["session_secret"]

    def test_the_price_is_itemised_and_formatted(self, api, catalogue):
        body = create_quote(api).json()
        item = body["items"][0]
        assert {"price_key", "label", "amount", "billing_kind"} <= set(item)
        assert item["amount"]["formatted"]

    def test_setup_and_monthly_totals_are_separate(self, api, catalogue):
        body = create_quote(api, features=["appointment"]).json()
        assert body["subtotal_once"]["amount_minor"] > 0
        assert body["subtotal_recurring"]["amount_minor"] > 0

    def test_the_client_cannot_dictate_a_price(self, api, catalogue):
        """An injected amount must be ignored, not honoured."""
        honest = create_quote(api).json()["total"]["amount_minor"]
        tampered = create_quote(
            api, total_minor=1, subtotal_once_minor=1, items=[{"amount_minor": 1}]
        ).json()["total"]["amount_minor"]
        assert tampered == honest

    def test_auto_added_features_are_reported(self, api, catalogue):
        body = create_quote(api, features=["ai_assistant"]).json()
        assert "faq" in body["auto_added_features"]

    def test_multi_platform_is_priced_below_two_bots(self, api, catalogue):
        single = create_quote(api, platforms=["telegram"]).json()["total"]["amount_minor"]
        both = create_quote(api, platforms=["telegram", "bale"]).json()["total"]["amount_minor"]
        assert single < both < single * 2

    def test_an_undeliverable_combination_is_refused(self, api, catalogue):
        response = create_quote(
            api, template="restaurant", platforms=["bale"], features=["food_ordering"]
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "quote.feature_unavailable_on_platform"

    def test_iranian_pricing_is_shown_in_toman(self, api, catalogue):
        body = create_quote(api, currency="IRR").json()
        assert body["currency"] == "IRR"
        # Persian formatting renders IRR as Toman (ADR-0004).
        persian = api.get(
            f"{QUOTES}{body['id']}/?lang=fa",
            HTTP_X_QUOTE_SESSION=body["session_secret"],
        ).json()
        assert "تومان" in persian["total"]["formatted"]


class TestQuoteAccess:
    def test_the_session_secret_is_required_to_read_it_back(self, api, catalogue):
        body = create_quote(api).json()

        assert api.get(f"{QUOTES}{body['id']}/").status_code == 404
        assert (
            api.get(
                f"{QUOTES}{body['id']}/", HTTP_X_QUOTE_SESSION=body["session_secret"]
            ).status_code
            == 200
        )

    def test_the_secret_is_returned_only_once(self, api, catalogue):
        body = create_quote(api).json()
        fetched = api.get(
            f"{QUOTES}{body['id']}/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        ).json()
        assert "session_secret" not in fetched

    def test_a_quote_can_be_repriced_as_the_customer_changes_their_mind(self, api, catalogue):
        body = create_quote(api, features=[]).json()
        before = body["total"]["amount_minor"]

        updated = api.put(
            f"{QUOTES}{body['id']}/",
            {
                "template": "clinic",
                "platforms": ["telegram"],
                "features": ["appointment"],
                "currency": "USD",
            },
            format="json",
            HTTP_X_QUOTE_SESSION=body["session_secret"],
        ).json()

        assert updated["total"]["amount_minor"] > before
        assert updated["id"] == body["id"]

    def test_claiming_requires_authentication(self, api, catalogue):
        body = create_quote(api).json()
        response = api.post(
            f"{QUOTES}{body['id']}/claim/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )
        assert response.status_code == 401

    def test_an_authenticated_user_can_claim_into_their_workspace(
        self, api, auth_client, catalogue, tenant_a
    ):
        body = create_quote(api).json()
        response = auth_client.post(
            f"{QUOTES}{body['id']}/claim/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )
        assert response.status_code == 200
        assert response.json()["is_claimed"] is True

    def test_another_tenant_cannot_read_a_claimed_quote(
        self, api, auth_client, other_client, catalogue, tenant_a, tenant_b
    ):
        body = create_quote(api).json()
        auth_client.post(
            f"{QUOTES}{body['id']}/claim/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )

        response = other_client.get(
            f"{QUOTES}{body['id']}/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )
        assert response.status_code == 404


class TestPreviewEndpoint:
    def test_a_visitor_can_preview_before_paying(self, api, catalogue):
        body = create_quote(api, features=["appointment"]).json()

        response = api.get(
            f"{QUOTES}{body['id']}/preview/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )
        assert response.status_code == 200

        platforms = response.json()["platforms"]
        assert platforms[0]["platform"] == "telegram"
        assert platforms[0]["screens"]

    def test_the_preview_covers_every_purchased_platform(self, api, catalogue):
        body = create_quote(api, platforms=["telegram", "bale"]).json()
        response = api.get(
            f"{QUOTES}{body['id']}/preview/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )
        assert {p["platform"] for p in response.json()["platforms"]} == {"telegram", "bale"}

    def test_the_preview_needs_the_session_secret(self, api, catalogue):
        body = create_quote(api).json()
        assert api.get(f"{QUOTES}{body['id']}/preview/").status_code == 404

    def test_the_business_name_appears_in_the_preview(self, api, catalogue):
        body = create_quote(api, business={"name": "Tehran Smile Clinic"}).json()
        response = api.get(
            f"{QUOTES}{body['id']}/preview/", HTTP_X_QUOTE_SESSION=body["session_secret"]
        )
        first_screen = response.json()["platforms"][0]["screens"][0]
        assert "Tehran Smile Clinic" in first_screen["message"]["text"]

    def test_previewing_does_not_create_a_bot(self, api, catalogue):
        """Nothing may be activated before payment (spec §48)."""
        body = create_quote(api).json()
        api.get(f"{QUOTES}{body['id']}/preview/", HTTP_X_QUOTE_SESSION=body["session_secret"])

        from apps.orders.models import Quote

        quote = Quote.objects.get(public_id=body["id"])
        assert quote.converted_order_id is None
