from __future__ import annotations

from rest_framework import permissions, viewsets

from apps.business_templates.api.serializers import BusinessTemplateSerializer
from apps.business_templates.models import BusinessTemplate


class BusinessTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """Public template catalogue — the builder's first step."""

    serializer_class = BusinessTemplateSerializer
    permission_classes = (permissions.AllowAny,)
    pagination_class = None
    lookup_field = "slug"
    queryset = BusinessTemplate.objects.filter(is_active=True).prefetch_related(
        "template_features__feature"
    )

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["locale"] = getattr(self.request, "locale", "en")
        return context
