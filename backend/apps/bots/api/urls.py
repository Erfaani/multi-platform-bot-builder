from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.bots.api.views import BotViewSet

router = DefaultRouter()
router.register("bots", BotViewSet, basename="bot")

urlpatterns = [path("", include(router.urls))]
