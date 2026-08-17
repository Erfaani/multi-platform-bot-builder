from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.errors import NotFoundError
from apps.customers.resolution import resolve_active_tenant
from apps.orders.models import Order
from apps.payments.api.serializers import (
    PaymentMethodSerializer,
    PaymentSerializer,
    StartPaymentSerializer,
    SubmitProofSerializer,
)
from apps.payments.models import PaymentMethod
from apps.payments.services import (
    available_methods,
    get_payment_for_tenant,
    start_payment,
    submit_proof,
)


def _client_ip(request: Request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class PaymentMethodListView(APIView):
    """Methods usable for a specific order.

    Scoped to the order rather than listed globally, because currency and minimum
    amount decide what is actually offerable — a global list would show options that
    fail at the next step.
    """

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=PaymentMethodSerializer(many=True))
    def get(self, request: Request, order_public_id: str) -> Response:
        tenant = resolve_active_tenant(request).tenant
        order = Order.objects.filter(public_id=order_public_id, tenant=tenant).first()
        if order is None:
            raise NotFoundError()

        methods = available_methods(
            currency=order.currency,
            country=tenant.country or "",
            amount_minor=order.total_minor,
        )
        return Response(
            PaymentMethodSerializer(
                methods,
                many=True,
                context={"locale": getattr(request, "locale", "en")},
            ).data
        )


class PaymentViewSet(viewsets.GenericViewSet):
    """Customer payment attempts."""

    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"
    # Multipart is enabled only on `proof`, which is the sole file endpoint. Applying
    # it viewset-wide would reject ordinary JSON requests with a 415.

    def get_serializer_context(self) -> dict:
        return {
            **super().get_serializer_context(),
            "locale": getattr(self.request, "locale", "en"),
        }

    def _tenant(self):
        return resolve_active_tenant(self.request).tenant

    @extend_schema(request=StartPaymentSerializer, responses={201: PaymentSerializer})
    def create(self, request: Request) -> Response:
        """Open a payment against an order and return its instructions."""
        serializer = StartPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = self._tenant()
        order = Order.objects.filter(
            public_id=request.data.get("order"), tenant=tenant
        ).first()
        if order is None:
            raise NotFoundError()

        method = PaymentMethod.objects.filter(
            public_id=serializer.validated_data["payment_method"], is_enabled=True
        ).first()
        if method is None:
            raise NotFoundError(code="payment.method_not_found")

        payment = start_payment(order=order, method=method, user=request.user)
        return Response(
            PaymentSerializer(payment, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=PaymentSerializer)
    def retrieve(self, request: Request, public_id: str) -> Response:
        payment = get_payment_for_tenant(public_id=public_id, tenant=self._tenant())
        return Response(
            PaymentSerializer(payment, context=self.get_serializer_context()).data
        )

    @extend_schema(request=SubmitProofSerializer, responses=PaymentSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="proof",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
        throttle_classes=[ScopedRateThrottle],
    )
    def proof(self, request: Request, public_id: str) -> Response:
        """Upload proof of payment (receipt file and/or transaction hash)."""
        payment = get_payment_for_tenant(public_id=public_id, tenant=self._tenant())

        serializer = SubmitProofSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = submit_proof(
            payment=payment,
            user=request.user,
            upload=data.get("file"),
            tx_hash=data.get("tx_hash", ""),
            sender_wallet=data.get("sender_wallet", ""),
            payer_note=data.get("payer_note", ""),
            ip=_client_ip(request),
        )
        return Response(
            PaymentSerializer(payment, context=self.get_serializer_context()).data
        )

    proof.throttle_scope = "upload"
