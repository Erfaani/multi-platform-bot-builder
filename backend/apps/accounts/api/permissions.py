"""Permission classes for platform-staff scopes.

Every admin route declares the minimum scope it needs (API.md §9); there is no
"authenticated means allowed".
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView


class HasStaffScope(permissions.BasePermission):
    """Grants access when the user holds ``required_scope`` on the view."""

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False

        required = getattr(view, "required_scope", None)
        if required is None:
            raise AssertionError(
                f"{type(view).__name__} uses HasStaffScope but declares no `required_scope`."
            )

        from apps.accounts.services import has_scope

        return has_scope(user, required)


class IsEmailVerified(permissions.BasePermission):
    """Required before money can change hands (SECURITY.md §2)."""

    message = "Please verify your email address first."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_email_verified)


class IsSelf(permissions.BasePermission):
    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        return obj == request.user
