from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.bots.models import Bot
from apps.core.errors import NotFoundError
from apps.customers.resolution import resolve_active_tenant
from apps.support.api.serializers import (
    SupportTicketDetailSerializer,
    SupportTicketSerializer,
    TicketCreateSerializer,
    TicketReplySerializer,
)
from apps.support.models import SupportTicket
from apps.support.services import close_ticket, create_ticket, get_ticket_for_tenant, reply_to_ticket


class SupportTicketViewSet(viewsets.GenericViewSet):
    """The customer's support conversations with the platform."""

    serializer_class = SupportTicketSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def _tenant(self):
        return resolve_active_tenant(self.request).tenant

    def get_serializer_context(self) -> dict:
        return {**super().get_serializer_context(), "request": self.request}

    def get_queryset(self):
        return SupportTicket.objects.filter(tenant=self._tenant()).select_related("bot", "created_by")

    def _load(self, public_id: str):
        return get_ticket_for_tenant(public_id=public_id, tenant=self._tenant())

    @extend_schema(responses=SupportTicketSerializer(many=True))
    def list(self, request: Request) -> Response:
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @extend_schema(responses=SupportTicketDetailSerializer)
    def retrieve(self, request: Request, public_id: str) -> Response:
        ticket = self._load(public_id)
        return Response(
            SupportTicketDetailSerializer(ticket, context=self.get_serializer_context()).data
        )

    @extend_schema(request=TicketCreateSerializer, responses={201: SupportTicketDetailSerializer})
    def create(self, request: Request) -> Response:
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = self._tenant()
        bot = None
        if data.get("bot"):
            bot = Bot.objects.filter(public_id=data["bot"], tenant=tenant).first()
            if bot is None:
                raise NotFoundError(code="support.bot_not_found")

        ticket = create_ticket(
            tenant=tenant, actor=request.user, subject=data["subject"], body=data["body"], bot=bot
        )
        return Response(
            SupportTicketDetailSerializer(ticket, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=TicketReplySerializer,
        responses={201: SupportTicketDetailSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="reply",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def reply(self, request: Request, public_id: str) -> Response:
        ticket = self._load(public_id)

        serializer = TicketReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        reply_to_ticket(ticket=ticket, actor=request.user, body=data["body"], upload=data.get("file"))
        ticket.refresh_from_db()
        return Response(
            SupportTicketDetailSerializer(ticket, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=SupportTicketSerializer)
    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request: Request, public_id: str) -> Response:
        ticket = close_ticket(ticket=self._load(public_id), actor=request.user)
        return Response(self.get_serializer(ticket).data)
