from django.urls import path

from apps.accounts.api.views import (
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
    VerifyEmailView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("email/verify/", VerifyEmailView.as_view(), name="auth-verify-email"),
]
