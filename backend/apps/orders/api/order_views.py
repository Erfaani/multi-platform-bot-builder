from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.viewsets import TenantScopedReadOnlyViewSet
from apps.core.errors import NotFoundError
from apps.orders.api.order_serializers import (
    CancelOrderSerializer,
    OrderSerializer,
    OrderSummarySerializer,
    PlaceOrderSerializer,
)
from apps.orders.models import Order, Quote
from apps.orders.services import cancel_order, place_order


class OrderViewSet(TenantScopedReadOnlyViewSet):
    """Customer-facing orders.

    Read-only plus explicit actions: an order's status is never assigned through a
    PATCH. Every move goes through the state machine (`orders/domain/state_machine.py`).
    """

    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAuthenticated,)
    queryset = Order.objects.select_related("template", "tenant").prefetch_related(
        "items", "events", "payments__payment_method"
    )

    def get_serializer_class(self):
        return OrderSummarySerializer if self.action == "list" else OrderSerializer

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["locale"] = getattr(self.request, "locale", "en")
        return context

    @extend_schema(request=PlaceOrderSerializer, responses={201: OrderSerializer})
    def create(self, request: Request) -> Response:
        """Convert a claimed quote into an order.

        Re-submitting the same quote returns the existing order rather than creating a
        second one, so a double-clicked checkout button cannot double-charge.
        """
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = self.get_tenant()
        quote = Quote.objects.filter(
            public_id=serializer.validated_data["quote"], tenant=tenant
        ).first()
        if quote is None:
            raise NotFoundError(
                code="order.quote_not_found",
                message="That quote was not found in this workspace. Claim it first.",
            )

        order = place_order(quote=quote, tenant=tenant, user=request.user)
        return Response(
            OrderSerializer(order, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=CancelOrderSerializer, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, public_id: str) -> Response:
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = cancel_order(
            order=self.get_object(),
            user=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)
