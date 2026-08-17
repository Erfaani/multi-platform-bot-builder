"""Authentication classes.

Locale resolution has to happen twice, and this is the second half. Django middleware
runs before DRF authenticates, so a token-authenticated caller is still anonymous when
:class:`apps.core.middleware.LocaleResolutionMiddleware` runs and their stored
preference is invisible. Authentication is the first moment the user is known, so it
is the right place to apply it.

Precedence stays as documented in I18N.md §2: an explicit ``?lang=`` always wins,
otherwise the user's saved preference beats the cookie and ``Accept-Language``.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import translation
from rest_framework_simplejwt.authentication import JWTAuthentication


class LocaleAwareJWTAuthentication(JWTAuthentication):
    """JWT authentication that activates the authenticated user's locale."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _token = result
            self._apply_user_locale(request, user)
        return result

    @staticmethod
    def _apply_user_locale(request, user) -> None:
        # An explicit ?lang= is a deliberate override and must not be undone.
        if getattr(request, "locale_source", None) == "query":
            return

        preferred = getattr(user, "preferred_locale", None)
        if preferred not in settings.ACTIVE_LOCALES:
            return

        translation.activate(preferred)
        # Written on the underlying HttpRequest so the middleware, which holds a
        # reference to that object rather than to DRF's wrapper, sees the change.
        underlying = getattr(request, "_request", request)
        underlying.locale = preferred
        underlying.locale_source = "user"
