from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.features.api.views import FeatureViewSet, PlatformListView

router = DefaultRouter()
router.register("features", FeatureViewSet, basename="feature")

urlpatterns = [
    path("platforms/", PlatformListView.as_view(), name="platform-list"),
    path("", include(router.urls)),
]
