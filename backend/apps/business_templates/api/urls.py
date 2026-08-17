from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.business_templates.api.views import BusinessTemplateViewSet

router = DefaultRouter()
router.register("templates", BusinessTemplateViewSet, basename="template")

urlpatterns = [path("", include(router.urls))]
