from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.customers.api.views import InvitationViewSet, TenantViewSet

router = DefaultRouter()
router.register("tenants", TenantViewSet, basename="tenant")
router.register("invitations", InvitationViewSet, basename="invitation")

urlpatterns = [path("", include(router.urls))]
