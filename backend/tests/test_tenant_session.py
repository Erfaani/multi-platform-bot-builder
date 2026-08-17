"""`apps.core.tenant_session._reset_session` — the `request_finished` handler that
clears per-request RLS state from a pooled connection (`CONN_MAX_AGE`).

Caught live while testing something else in Phase 10: the original version called
`RESET ROLE` unconditionally. `RESET ROLE` reverts to `session_user`, i.e. the
*connecting* role — but the privilege drop in `_drop_privileges` is connection-lifetime,
set once on `connection_created`, which does not fire again for a connection Django is
reusing. So the original code silently restored full owner privileges (bypassing RLS
entirely) for every request after the first one on any pooled connection. It also always
opened a cursor, even for a request that never scoped a tenant at all — meaning a pooled
connection left open by an earlier, unrelated request made even `/healthz` (deliberately
DB-free by design; see `apps.core.health`) pay for a DB round trip it has nothing to do
with. Both are fixed the same way: only touch the database when this request actually
called `set_current_tenant()`, and never touch the role.
"""

from __future__ import annotations

import pytest
from django.db import connection

from apps.core import tenant_session
from apps.core.request_context import set_active_tenant

pytestmark = pytest.mark.django_db


class TestResetSessionNeverRevertsTheRoleDrop:
    def test_the_dropped_role_survives_a_request_finished_reset(self, provisioned_bot):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE botbuilder_app")

            set_active_tenant(provisioned_bot.tenant)
            tenant_session._reset_session(sender=None)

            cursor.execute("SELECT current_user")
            assert cursor.fetchone()[0] == "botbuilder_app"


class TestResetSessionSkipsTheDatabaseWhenNothingWasScoped:
    def test_no_query_runs_when_this_request_never_set_a_tenant(self, django_assert_num_queries):
        set_active_tenant(None)

        with django_assert_num_queries(0):
            tenant_session._reset_session(sender=None)

    def test_the_contextvar_is_still_cleared_either_way(self, provisioned_bot):
        from apps.core.request_context import get_active_tenant

        set_active_tenant(provisioned_bot.tenant)
        tenant_session._reset_session(sender=None)

        assert get_active_tenant() is None
