"""The in-app notification inbox (spec §30)."""

from __future__ import annotations

import pytest

from apps.notifications.models import Notification
from apps.notifications.services import mark_all_read, mark_read, unread_count

pytestmark = pytest.mark.django_db


def _notify(user, tenant=None, event_type="order.paid") -> Notification:
    return Notification.objects.create(
        recipient=user,
        tenant=tenant,
        event_type=event_type,
        title_key="notification.order_paid.title",
        body_key="notification.order_paid.body",
    )


class TestUnreadCount:
    def test_counts_only_unread(self, user):
        _notify(user)
        read = _notify(user)
        mark_read(notification=read)

        assert unread_count(user) == 1


class TestMarkAllRead:
    def test_marks_every_unread_notification(self, user):
        _notify(user)
        _notify(user)
        _notify(user)

        marked = mark_all_read(user)

        assert marked == 3
        assert unread_count(user) == 0

    def test_does_not_touch_another_users_notifications(self, user, other_user):
        _notify(user)
        _notify(other_user)

        mark_all_read(user)

        assert unread_count(user) == 0
        assert unread_count(other_user) == 1

    def test_is_idempotent(self, user):
        _notify(user)
        mark_all_read(user)
        assert mark_all_read(user) == 0


class TestNotificationApi:
    def test_owner_sees_only_their_own_notifications(self, auth_client, user, other_user):
        mine = _notify(user)
        _notify(other_user)

        response = auth_client.get("/api/v1/notifications/")
        assert response.status_code == 200
        results = response.json()["results"]
        ids = {row["id"] for row in results}
        assert str(mine.public_id) in ids
        assert len(results) == 1

    def test_unread_count_endpoint(self, auth_client, user):
        _notify(user)
        _notify(user)

        response = auth_client.get("/api/v1/notifications/unread-count/")
        assert response.status_code == 200
        assert response.json()["unread"] == 2

    def test_read_all_endpoint(self, auth_client, user):
        _notify(user)
        _notify(user)

        response = auth_client.post("/api/v1/notifications/read-all/")
        assert response.status_code == 200
        assert response.json()["marked"] == 2
        assert unread_count(user) == 0

    def test_read_all_does_not_affect_other_users(self, auth_client, user, other_user):
        _notify(other_user)

        auth_client.post("/api/v1/notifications/read-all/")

        assert unread_count(other_user) == 1

    def test_unauthenticated_is_rejected(self, api):
        assert api.get("/api/v1/notifications/").status_code == 401
        assert api.post("/api/v1/notifications/read-all/").status_code == 401
