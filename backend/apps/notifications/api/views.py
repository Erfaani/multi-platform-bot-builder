from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.notifications.messages import render
from apps.notifications.models import Notification
from apps.notifications.services import mark_all_read, mark_read, unread_count


class NotificationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    title = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = ("id", "event_type", "title", "body", "link", "is_read", "created_at")

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_title(self, obj: Notification) -> str:
        return render(obj.title_key, obj.params, self._locale())

    def get_body(self, obj: Notification) -> str:
        return render(obj.body_key, obj.params, self._locale())


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """The caller's own notifications.

    Scoped by recipient rather than by tenant: a notification is addressed to a person,
    and a workspace colleague should not read someone else's inbox.
    """

    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    def get_serializer_context(self) -> dict:
        return {
            **super().get_serializer_context(),
            "locale": getattr(self.request, "locale", "en"),
        }

    @extend_schema(responses={200: None})
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread(self, request: Request) -> Response:
        return Response({"unread": unread_count(request.user)})

    @extend_schema(responses=NotificationSerializer)
    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request: Request, public_id: str) -> Response:
        notification = mark_read(notification=self.get_object())
        return Response(self.get_serializer(notification).data)

    @extend_schema(responses={200: None})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request: Request) -> Response:
        return Response({"marked": mark_all_read(request.user)})
