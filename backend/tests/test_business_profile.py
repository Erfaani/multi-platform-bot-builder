"""Business profile editing and FAQ CRUD (spec §24, Phase 6 exit criterion).

`provisioned_bot` already carries the business snapshot the saga wrote at
provisioning time — these tests exercise the dashboard's write path on top of it.
"""

from __future__ import annotations

import pytest

from apps.businesses.models import BusinessProfile, FaqEntry, WorkingHours

pytestmark = pytest.mark.django_db


def _bot_url(bot, suffix: str = "") -> str:
    return f"/api/v1/bots/{bot.public_id}/{suffix}"


def _test_image(name: str = "logo.png") -> "SimpleUploadedFile":
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class TestBusinessProfile:
    def test_a_provisioned_bot_already_has_a_profile(self, provisioned_bot):
        """The saga seeds it from the quote's business snapshot — never a blank page."""
        profile = BusinessProfile.objects.get(bot=provisioned_bot)
        assert profile.display_name == "Tehran Smile Clinic"
        assert profile.phone == "+98 21 1234 5678"

    def test_owner_can_read_the_profile(self, auth_client, provisioned_bot):
        response = auth_client.get(_bot_url(provisioned_bot, "business-profile/"))
        assert response.status_code == 200
        assert response.json()["display_name"] == "Tehran Smile Clinic"

    def test_owner_can_edit_the_profile(self, auth_client, provisioned_bot):
        response = auth_client.patch(
            _bot_url(provisioned_bot, "business-profile/"),
            {"phone": "+98 21 9999 0000", "description": "Now with braces."},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["phone"] == "+98 21 9999 0000"
        assert body["description"] == "Now with braces."

    def test_editing_the_profile_bumps_the_runtime_cache_version(self, auth_client, provisioned_bot):
        before = provisioned_bot.configuration.version
        auth_client.patch(
            _bot_url(provisioned_bot, "business-profile/"), {"city": "Tehran"}, format="json"
        )
        provisioned_bot.configuration.refresh_from_db()
        assert provisioned_bot.configuration.version > before

    def test_a_stranger_cannot_read_another_tenants_profile(self, other_client, provisioned_bot):
        response = other_client.get(_bot_url(provisioned_bot, "business-profile/"))
        assert response.status_code == 404

    def test_unauthenticated_is_rejected(self, api, provisioned_bot):
        response = api.get(_bot_url(provisioned_bot, "business-profile/"))
        assert response.status_code == 401


class TestBusinessLogo:
    def test_owner_can_upload_a_logo(self, auth_client, provisioned_bot):
        response = auth_client.post(
            _bot_url(provisioned_bot, "business-profile/logo/"),
            {"file": _test_image()},
            format="multipart",
        )
        assert response.status_code == 200
        assert response.json()["logo_url"].startswith("/media/public/logos/")

        profile = BusinessProfile.objects.get(bot=provisioned_bot)
        assert profile.logo.name.startswith("public/logos/")

    def test_uploading_a_new_logo_replaces_the_old_file(self, auth_client, provisioned_bot):
        auth_client.post(
            _bot_url(provisioned_bot, "business-profile/logo/"),
            {"file": _test_image("first.png")},
            format="multipart",
        )
        first_name = BusinessProfile.objects.get(bot=provisioned_bot).logo.name

        auth_client.post(
            _bot_url(provisioned_bot, "business-profile/logo/"),
            {"file": _test_image("second.png")},
            format="multipart",
        )
        second_name = BusinessProfile.objects.get(bot=provisioned_bot).logo.name
        assert second_name != first_name

    def test_a_stranger_cannot_upload_a_logo(self, other_client, provisioned_bot):
        response = other_client.post(
            _bot_url(provisioned_bot, "business-profile/logo/"),
            {"file": _test_image()},
            format="multipart",
        )
        assert response.status_code == 404


class TestWorkingHours:
    def test_defaults_to_an_empty_week(self, auth_client, provisioned_bot):
        response = auth_client.get(_bot_url(provisioned_bot, "working-hours/"))
        assert response.status_code == 200
        assert response.json()["days"] == []

    def test_owner_can_set_the_whole_week(self, auth_client, provisioned_bot):
        days = [
            {"weekday": weekday, "opens_at": "09:00", "closes_at": "17:00", "is_closed": False}
            for weekday in range(5)
        ] + [
            {"weekday": 5, "opens_at": None, "closes_at": None, "is_closed": True},
            {"weekday": 6, "opens_at": None, "closes_at": None, "is_closed": True},
        ]
        response = auth_client.put(
            _bot_url(provisioned_bot, "working-hours/"), {"days": days}, format="json"
        )
        assert response.status_code == 200
        assert len(response.json()["days"]) == 7
        assert WorkingHours.objects.filter(bot=provisioned_bot).count() == 7

    def test_setting_the_week_replaces_any_previous_rows(self, auth_client, provisioned_bot):
        auth_client.put(
            _bot_url(provisioned_bot, "working-hours/"),
            {"days": [{"weekday": 0, "opens_at": "09:00", "closes_at": "17:00", "is_closed": False}]},
            format="json",
        )
        auth_client.put(
            _bot_url(provisioned_bot, "working-hours/"),
            {"days": [{"weekday": 1, "opens_at": "10:00", "closes_at": "18:00", "is_closed": False}]},
            format="json",
        )
        rows = WorkingHours.objects.filter(bot=provisioned_bot)
        assert rows.count() == 1
        assert rows.first().weekday == 1

    def test_a_closed_day_needs_no_times(self, auth_client, provisioned_bot):
        response = auth_client.put(
            _bot_url(provisioned_bot, "working-hours/"),
            {"days": [{"weekday": 0, "opens_at": None, "closes_at": None, "is_closed": True}]},
            format="json",
        )
        assert response.status_code == 200

    def test_an_open_day_rejects_a_backwards_range(self, auth_client, provisioned_bot):
        response = auth_client.put(
            _bot_url(provisioned_bot, "working-hours/"),
            {"days": [{"weekday": 0, "opens_at": "17:00", "closes_at": "09:00", "is_closed": False}]},
            format="json",
        )
        assert response.status_code == 400

    def test_a_stranger_cannot_read_working_hours(self, other_client, provisioned_bot):
        response = other_client.get(_bot_url(provisioned_bot, "working-hours/"))
        assert response.status_code == 404


class TestFaqCrud:
    def test_create_list_and_delete(self, auth_client, provisioned_bot):
        create = auth_client.post(
            _bot_url(provisioned_bot, "faq/"),
            {"question": "Do you take walk-ins?", "answer": "Yes, weekdays only."},
            format="json",
        )
        assert create.status_code == 201
        faq_id = create.json()["id"]

        listed = auth_client.get(_bot_url(provisioned_bot, "faq/"))
        assert listed.status_code == 200
        assert any(item["id"] == faq_id for item in listed.json())

        deleted = auth_client.delete(_bot_url(provisioned_bot, f"faq/{faq_id}/"))
        assert deleted.status_code == 204
        assert not FaqEntry.objects.filter(pk=faq_id).exists()

    def test_create_requires_both_fields(self, auth_client, provisioned_bot):
        response = auth_client.post(
            _bot_url(provisioned_bot, "faq/"), {"question": "", "answer": ""}, format="json"
        )
        assert response.status_code == 400

    def test_update_changes_the_answer(self, auth_client, provisioned_bot):
        entry = FaqEntry.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, question="Q", answer="old"
        )
        response = auth_client.patch(
            _bot_url(provisioned_bot, f"faq/{entry.pk}/"), {"answer": "new"}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "new"

    def test_editing_faq_bumps_the_runtime_cache_version(self, auth_client, provisioned_bot):
        before = provisioned_bot.configuration.version
        auth_client.post(
            _bot_url(provisioned_bot, "faq/"),
            {"question": "Parking?", "answer": "Yes, free."},
            format="json",
        )
        provisioned_bot.configuration.refresh_from_db()
        assert provisioned_bot.configuration.version > before

    def test_a_stranger_cannot_touch_another_tenants_faq(self, other_client, provisioned_bot):
        entry = FaqEntry.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, question="Q", answer="A"
        )
        response = other_client.patch(
            _bot_url(provisioned_bot, f"faq/{entry.pk}/"), {"answer": "hijacked"}, format="json"
        )
        assert response.status_code == 404
        entry.refresh_from_db()
        assert entry.answer == "A"


class TestRuntimeReflectsProfileEdits:
    """The point of Phase 6: an edit is live on the very next message, no redeploy."""

    def test_the_bot_answers_with_the_edited_phone_number(self, auth_client, provisioned_bot, fake_transport):
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate

        auth_client.patch(
            _bot_url(provisioned_bot, "business-profile/"),
            {"phone": "+98 21 5555 1111"},
            format="json",
        )

        instance = provisioned_bot.instances.get(platform="telegram")
        payload = {
            "update_id": 900,
            "message": {
                "message_id": 900,
                "text": "Contact",
                "chat": {"id": 1},
                "from": {"id": 1, "first_name": "Ada", "username": "ada", "language_code": "en"},
            },
        }
        update = InboundUpdate.objects.create(instance=instance, platform_update_id=900, raw=payload)
        result = dispatch_update(update)

        assert "+98 21 5555 1111" in result.reply_text
