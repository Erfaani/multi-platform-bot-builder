from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.core.api.views import CurrencyViewSet, PublicSettingsView

router = DefaultRouter()
router.register("currencies", CurrencyViewSet, basename="currency")

urlpatterns = [
    path("settings/public/", PublicSettingsView.as_view(), name="public-settings"),
    path("", include(router.urls)),
]
