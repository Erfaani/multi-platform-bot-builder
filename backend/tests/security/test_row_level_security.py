"""Proves the PostgreSQL policies from `apps.core`'s `0002_row_level_security` migration
actually isolate tenants for the unprivileged `botbuilder_app` role — a second, independent
layer *beneath* the application-level `.for_tenant()` filtering `test_cross_tenant.py`
already proves (ADR-0005). This file talks to the database directly with `SET ROLE`,
bypassing the ORM's own scoping entirely, which is the whole point: even a bug in
application code, or hand-written SQL, must not be able to see or touch another tenant's
row once the connection has dropped into `botbuilder_app`.

`SET LOCAL` throughout (both `SET LOCAL ROLE` and `set_config(..., true)`) — never plain
`SET` — so every change is transaction-scoped and reverts automatically on this test's own
rollback (pytest-django wraps every test in one transaction). Nothing here can leak into
another test on the same connection, and no manual cleanup is needed.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.utils import DatabaseError

pytestmark = pytest.mark.django_db


class TestRowLevelSecurity:
    def test_the_app_role_sees_nothing_without_a_tenant_set(self, provisioned_bot):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE botbuilder_app")
            cursor.execute("SELECT count(*) FROM bot")
            assert cursor.fetchone()[0] == 0

    def test_the_app_role_sees_only_the_scoped_tenants_bot(self, provisioned_bot, tenant_b):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE botbuilder_app")

            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", [str(provisioned_bot.tenant_id)]
            )
            cursor.execute("SELECT count(*) FROM bot")
            assert cursor.fetchone()[0] == 1

            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_b.pk)])
            cursor.execute("SELECT count(*) FROM bot")
            assert cursor.fetchone()[0] == 0

    def test_the_app_role_cannot_reassign_a_row_to_another_tenant(self, provisioned_bot, tenant_b):
        """`WITH CHECK`, not just `USING` — the policy blocks the write, not only the read."""
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE botbuilder_app")
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", [str(provisioned_bot.tenant_id)]
            )
            with pytest.raises(DatabaseError):
                cursor.execute(
                    "UPDATE bot SET tenant_id = %s WHERE id = %s",
                    [tenant_b.pk, provisioned_bot.pk],
                )

    def test_the_unscoped_dev_connection_is_unaffected(self, provisioned_bot):
        """The default (no `SET ROLE`) connection — what every other test in this suite
        runs as — keeps full owner privileges and is not filtered by these policies at
        all; that is by design (see the migration's docstring), not a gap this test
        papers over."""
        from apps.bots.models import Bot

        assert Bot.objects.filter(pk=provisioned_bot.pk).exists()
