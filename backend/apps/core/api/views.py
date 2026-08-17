from django.conf import settings as django_settings
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import CurrencySerializer, PublicSettingsSerializer
from apps.core.models import Currency, SystemSetting


class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    """Active currencies and their formatting metadata (API.md §3)."""

    serializer_class = CurrencySerializer
    permission_classes = (permissions.AllowAny,)
    pagination_class = None
    lookup_field = "code"
    queryset = Currency.objects.filter(is_active=True)


class PublicSettingsView(APIView):
    """Platform configuration safe for unauthenticated clients (spec §51).

    Only settings explicitly flagged ``is_public`` are exposed; secrets live in the
    environment and never reach this table (SECURITY.md §12).
    """

    permission_classes = (permissions.AllowAny,)

    @extend_schema(responses=PublicSettingsSerializer)
    def get(self, request) -> Response:
        public = {row.key: row.value for row in SystemSetting.objects.filter(is_public=True)}
        payload = {
            "brand_name": public.get("brand_name", "Bot Builder Platform"),
            "default_locale": django_settings.LANGUAGE_CODE,
            "active_locales": django_settings.ACTIVE_LOCALES,
            "rtl_locales": sorted(django_settings.RTL_LANGUAGES),
            "default_currency": django_settings.DEFAULT_CURRENCY,
            "maintenance_mode": django_settings.MAINTENANCE_MODE,
            "settings": public,
        }
        return Response(PublicSettingsSerializer(payload).data)
