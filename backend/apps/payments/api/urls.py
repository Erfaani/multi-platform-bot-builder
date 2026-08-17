from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.payments.api.views import PaymentMethodListView, PaymentViewSet

router = DefaultRouter()
router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path(
        "orders/<uuid:order_public_id>/payment-methods/",
        PaymentMethodListView.as_view(),
        name="order-payment-methods",
    ),
    path("", include(router.urls)),
]
