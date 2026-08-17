from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.orders.api.order_views import OrderViewSet
from apps.orders.api.views import QuoteViewSet

router = DefaultRouter()
router.register("quotes", QuoteViewSet, basename="quote")
router.register("orders", OrderViewSet, basename="order")

urlpatterns = [path("", include(router.urls))]
