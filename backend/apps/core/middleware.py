"""Request middleware: trace ids, locale resolution, maintenance mode."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import translation

from apps.core.request_context import get_request_id, new_request_id, set_request_id


class RequestIDMiddleware:
    """Attach a trace id to every request, echoed in responses and error bodies."""

    HEADER = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.META.get(self.HEADER, "")
        # Never trust an inbound value verbatim — it lands in logs.
        request_id = incoming[:32] if incoming.isalnum() and incoming else new_request_id()
        set_request_id(request_id)
        request.request_id = request_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response["X-Request-ID"] = get_request_id()
        return response


class LocaleResolutionMiddleware:
    """Resolve the active locale (I18N.md §2).

    Order: ``?lang=`` → authenticated user's preference → cookie → ``Accept-Language``
    → platform default. Only locales in ``ACTIVE_LOCALES`` are honoured.

    Middleware runs *before* DRF authenticates, so a JWT caller is still anonymous
    here and their stored preference cannot be seen yet. This pass therefore resolves
    everything except the user preference and records where the answer came from;
    :class:`apps.accounts.authentication.LocaleAwareJWTAuthentication` refines it the
    moment the user is known. The response header is written afterwards, from
    whatever the final value turned out to be.
    """

    COOKIE = "locale"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def _resolve(self, request: HttpRequest) -> tuple[str, str]:
        """Return ``(locale, source)`` where source is query/session/cookie/header/default."""
        active = settings.ACTIVE_LOCALES
        default = settings.LANGUAGE_CODE

        explicit = request.GET.get("lang")
        if explicit in active:
            return explicit, "query"

        # Session-authenticated users (Django admin) are already resolved here;
        # token-authenticated ones are handled by the authentication class.
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            preferred = getattr(user, "preferred_locale", None)
            if preferred in active:
                return preferred, "user"

        cookie = request.COOKIES.get(self.COOKIE)
        if cookie in active:
            return cookie, "cookie"

        header = translation.get_language_from_request(request, check_path=False)
        if header in active:
            return header, "header"
        if header:
            base = header.split("-")[0]
            if base in active:
                return base, "header"

        return default, "default"

    def __call__(self, request: HttpRequest) -> HttpResponse:
        locale, source = self._resolve(request)
        translation.activate(locale)
        request.locale = locale  # type: ignore[attr-defined]
        request.locale_source = source  # type: ignore[attr-defined]
        try:
            response = self.get_response(request)
        finally:
            translation.deactivate()

        # Read back rather than reusing `locale`: authentication may have refined it.
        response["Content-Language"] = getattr(request, "locale", locale)
        response.setdefault("Vary", "Accept-Language")
        return response


class MaintenanceModeMiddleware:
    """Return 503 for writes while maintenance mode is on (spec §51).

    Reads and health checks stay available so operators can still see the system.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    ALWAYS_ALLOWED = ("/healthz", "/readyz", "/django-admin")

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (
            settings.MAINTENANCE_MODE
            and request.method not in self.SAFE_METHODS
            and not request.path.startswith(self.ALWAYS_ALLOWED)
        ):
            from apps.core.errors import MaintenanceModeError

            return JsonResponse(
                {
                    "error": {
                        "code": MaintenanceModeError.code,
                        "message": str(MaintenanceModeError.default_message),
                        "trace_id": get_request_id(),
                    }
                },
                status=503,
            )
        return self.get_response(request)
