from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.support.api.views import SupportTicketViewSet

router = DefaultRouter()
router.register("support/tickets", SupportTicketViewSet, basename="support-ticket")

urlpatterns = [path("", include(router.urls))]
