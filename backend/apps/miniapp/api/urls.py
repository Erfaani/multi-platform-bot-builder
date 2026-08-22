from django.urls import path

from apps.miniapp.api.views import (
    MiniAppAppointmentSlotsView,
    MiniAppBookAppointmentView,
    MiniAppContentView,
)

urlpatterns = [
    path(
        "miniapp/<str:instance_public_id>/content/",
        MiniAppContentView.as_view(),
        name="miniapp-content",
    ),
    path(
        "miniapp/<str:instance_public_id>/appointment-slots/",
        MiniAppAppointmentSlotsView.as_view(),
        name="miniapp-appointment-slots",
    ),
    path(
        "miniapp/<str:instance_public_id>/book/",
        MiniAppBookAppointmentView.as_view(),
        name="miniapp-book",
    ),
]
