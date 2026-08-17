from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.orders.api.serializers import (
    BuildQuoteSerializer,
    PreviewRequestSerializer,
    QuoteSerializer,
)
from apps.orders.services import build_quote, claim_quote, get_quote_for_request
from apps.platforms.preview.service import build_preview, preview_to_json

#: Header carrying the anonymous builder's bearer secret. Knowing a quote's public_id
#: is deliberately not enough to read it back (docs/01-ARCHITECTURE-REVIEW.md F-3).
SESSION_HEADER = "HTTP_X_QUOTE_SESSION"


class QuoteViewSet(viewsets.GenericViewSet):
    """The builder.

    Public by design: a visitor configures and prices a bot before creating an account
    (spec §44). Ownership is established later, by `claim`.
    """

    serializer_class = QuoteSerializer
    permission_classes = (permissions.AllowAny,)
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["locale"] = getattr(self.request, "locale", "en")
        return context

    def _session_secret(self, request: Request) -> str:
        return request.META.get(SESSION_HEADER, "")

    def _load(self, request: Request, public_id: str):
        user = request.user if request.user.is_authenticated else None
        return get_quote_for_request(
            public_id=public_id, session_secret=self._session_secret(request), user=user
        )

    @extend_schema(request=BuildQuoteSerializer, responses={201: QuoteSerializer})
    def create(self, request: Request) -> Response:
        serializer = BuildQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        quote, auto_added = build_quote(
            template_slug=data["template"],
            platforms=data["platforms"],
            feature_slugs=data.get("features", []),
            currency=data.get("currency"),
            country=data.get("country", ""),
            locale=getattr(request, "locale", "en"),
            business_draft=data.get("business", {}),
            created_via=data.get("created_via"),
            user=request.user if request.user.is_authenticated else None,
        )

        payload = self.get_serializer(quote).data
        payload["auto_added_features"] = auto_added
        # Returned once, on creation. The client stores it and sends it back as
        # X-Quote-Session; it is never included in subsequent representations.
        payload["session_secret"] = quote.session_secret
        return Response(payload, status=status.HTTP_201_CREATED)

    @extend_schema(responses=QuoteSerializer)
    def retrieve(self, request: Request, public_id: str) -> Response:
        return Response(self.get_serializer(self._load(request, public_id)).data)

    @extend_schema(request=BuildQuoteSerializer, responses=QuoteSerializer)
    def update(self, request: Request, public_id: str) -> Response:
        """Re-price an existing quote as the customer changes the configuration."""
        quote = self._load(request, public_id)

        serializer = BuildQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        quote, auto_added = build_quote(
            template_slug=data["template"],
            platforms=data["platforms"],
            feature_slugs=data.get("features", []),
            currency=data.get("currency"),
            country=data.get("country", ""),
            locale=getattr(request, "locale", "en"),
            business_draft=data.get("business", {}),
            created_via=data.get("created_via"),
            user=request.user if request.user.is_authenticated else None,
            quote=quote,
        )

        payload = self.get_serializer(quote).data
        payload["auto_added_features"] = auto_added
        return Response(payload)

    @extend_schema(request=PreviewRequestSerializer, responses={200: None})
    @action(detail=True, methods=["get", "post"], url_path="preview")
    def preview(self, request: Request, public_id: str) -> Response:
        """Render the bot as it will appear, per platform (spec §48).

        Never activates anything — it is a pure rendering of the configuration.
        """
        quote = self._load(request, public_id)

        business_name = (quote.business_draft or {}).get("name") or "Your Business"
        if request.method == "POST":
            serializer = PreviewRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            business_name = serializer.validated_data.get("business_name") or business_name

        previews = build_preview(
            feature_slugs=quote.resolved_features,
            platforms=quote.platforms,
            business_name=business_name,
            locale=getattr(request, "locale", quote.locale),
        )
        return Response({"quote": str(quote.public_id), "platforms": preview_to_json(previews)})

    @extend_schema(responses=QuoteSerializer)
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def claim(self, request: Request, public_id: str) -> Response:
        """Bind an anonymous quote to the caller's active workspace."""
        from apps.customers.resolution import resolve_active_tenant

        quote = self._load(request, public_id)
        active = resolve_active_tenant(request)
        quote = claim_quote(quote=quote, tenant=active.tenant, user=request.user)
        return Response(self.get_serializer(quote).data)
