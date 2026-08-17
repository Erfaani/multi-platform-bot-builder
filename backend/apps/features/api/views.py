from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.features.api.serializers import (
    FeatureSerializer,
    PlatformSerializer,
    platform_payload,
)
from apps.features.models import Feature
from apps.features.services import availability_matrix


class FeatureViewSet(viewsets.ReadOnlyModelViewSet):
    """The sellable feature catalogue. Public: the builder works without an account."""

    serializer_class = FeatureSerializer
    permission_classes = (permissions.AllowAny,)
    pagination_class = None
    lookup_field = "slug"
    queryset = Feature.objects.filter(is_active=True)

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["locale"] = getattr(self.request, "locale", "en")
        # One query for the whole matrix rather than one per feature.
        context["availability"] = availability_matrix()
        return context


class PlatformListView(APIView):
    permission_classes = (permissions.AllowAny,)

    @extend_schema(responses=PlatformSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(PlatformSerializer(platform_payload(), many=True).data)
