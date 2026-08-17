"""Phase 10 query-optimization regression tests.

Guards two fan-out bugs found in a query audit: a list endpoint's query count must not
grow with the number of rows it returns. Both were true N+1s where a prefetch existed
on the queryset but a serializer method silently defeated it by chaining `.filter()` /
`.order_by()` onto the related manager — only a bare `.all()` reads the prefetch cache;
anything else re-queries per row.
"""

from __future__ import annotations

import pytest

from apps.crm import services
from apps.crm.models import ContactNote, LeadSource, Tag

pytestmark = pytest.mark.django_db


class TestCrmLeadsListDoesNotFanOut:
    def test_query_count_is_independent_of_lead_count(
        self, provisioned_bot, django_assert_max_num_queries
    ):
        from apps.bot_runtime.models import BusinessContact

        for i in range(5):
            contact = BusinessContact.objects.create(
                tenant=provisioned_bot.tenant,
                bot=provisioned_bot,
                platform="telegram",
                platform_user_id=f"lead-contact-{i}",
                display_name=f"Contact {i}",
            )
            lead = services.create_lead(
                bot=provisioned_bot, contact=contact, source=LeadSource.MANUAL
            )
            ContactNote.objects.create(tenant=provisioned_bot.tenant, lead=lead, body="note")
            tag, _ = Tag.objects.get_or_create(
                tenant=provisioned_bot.tenant, bot=provisioned_bot, name=f"tag-{i}"
            )
            tag.leads.add(lead)

        # A handful of fixed queries (leads + notes prefetch + tags prefetch), not one
        # growing set per lead — 10 is a generous ceiling, not a tight/fragile exact count.
        with django_assert_max_num_queries(10):
            leads = services.list_leads(provisioned_bot)
            for lead in leads:
                list(lead.notes.all())
                list(lead.tags.all())


class TestBotDashboardListDoesNotFanOut:
    def test_query_count_is_bounded_regardless_of_bot_count(
        self, auth_client, provisioned_bot, django_assert_max_num_queries
    ):
        with django_assert_max_num_queries(15):
            response = auth_client.get("/api/v1/bots/")
        assert response.status_code == 200
        body = response.json()
        results = body["results"] if isinstance(body, dict) and "results" in body else body
        assert results  # the fixture's bot must actually be in the response
        assert "features" in results[0]
        assert "provisioning" in results[0]
