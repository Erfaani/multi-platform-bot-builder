from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.signals import user_logged_in, user_login_failed
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.api.serializers import (
    LoginSerializer,
    RefreshSerializer,
    RegisterSerializer,
    TokenPairSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from apps.accounts.services import issue_tokens, register_user, update_profile, verify_email
from apps.core.errors import AuthenticationError


def _client_ip(request: Request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class RegisterView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "auth"

    @extend_schema(request=RegisterSerializer, responses={201: TokenPairSerializer})
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = register_user(
            email=data["email"],
            password=data["password"],
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            preferred_locale=data.get("preferred_locale"),
            preferred_currency=data.get("preferred_currency"),
            country=data.get("country", ""),
            timezone_name=data.get("timezone", "UTC"),
            ip=_client_ip(request),
        )
        return Response(
            {**issue_tokens(user), "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "auth"

    @extend_schema(request=LoginSerializer, responses={200: TokenPairSerializer})
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        password = serializer.validated_data["password"]

        user = authenticate(request, username=email, password=password)
        if user is None or not user.is_active:
            user_login_failed.send(
                sender=__name__, credentials={"email": email}, request=request._request
            )
            # Generic on purpose: never reveal whether the account exists.
            raise AuthenticationError(
                code="accounts.invalid_credentials", message="Incorrect email or password."
            )

        user_logged_in.send(sender=user.__class__, request=request._request, user=user)
        return Response({**issue_tokens(user), "user": UserSerializer(user).data})


class RefreshView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "auth"

    @extend_schema(request=RefreshSerializer, responses={200: TokenPairSerializer})
    def post(self, request: Request) -> Response:
        # SimpleJWT's serializer performs the rotation and blacklists the presented
        # token when ROTATE_REFRESH_TOKENS / BLACKLIST_AFTER_ROTATION are on, so a
        # replayed refresh token fails — which is how theft surfaces (SECURITY.md §2).
        serializer = TokenRefreshSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, InvalidToken) as exc:
            raise AuthenticationError(
                code="accounts.invalid_refresh_token", message="Your session has expired."
            ) from exc

        payload = dict(serializer.validated_data)
        payload["access_expires_in"] = int(
            settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()
        )
        return Response(payload)


class LogoutView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(request=RefreshSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            pass  # already invalid; logging out is idempotent
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=UserSerializer)
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=UserSerializer, responses=UserSerializer)
    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = update_profile(user=request.user, **serializer.validated_data)
        return Response(UserSerializer(user).data)


class VerifyEmailView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "auth"

    @extend_schema(request=VerifyEmailSerializer, responses={200: UserSerializer})
    def post(self, request: Request) -> Response:
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = verify_email(raw_token=serializer.validated_data["token"])
        return Response(UserSerializer(user).data)
