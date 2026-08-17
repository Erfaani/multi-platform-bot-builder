"""Application error hierarchy.

Every error carries a stable machine ``code`` and a *translatable* message. The code is
part of the API contract; the message is what a customer reads (API.md §1).
Internal detail never reaches a client — it goes to the log with the trace id.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _


class AppError(Exception):
    """Base class for expected, customer-facing failures."""

    code: str = "error.unexpected"
    status_code: int = 400
    default_message = _("Something went wrong. Please try again.")

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.code
        self.details = details or {}
        self.field_errors = field_errors or {}
        super().__init__(str(self.message))


class ValidationError(AppError):
    code = "error.validation"
    status_code = 400
    default_message = _("Some of the submitted data is invalid.")


class AuthenticationError(AppError):
    code = "error.unauthenticated"
    status_code = 401
    default_message = _("Authentication is required.")


class PermissionDeniedError(AppError):
    code = "error.forbidden"
    status_code = 403
    default_message = _("You do not have permission to perform this action.")


class NotFoundError(AppError):
    """Also used for cross-tenant access — a 403 would confirm the object exists."""

    code = "error.not_found"
    status_code = 404
    default_message = _("The requested resource was not found.")


class ConflictError(AppError):
    code = "error.conflict"
    status_code = 409
    default_message = _("This action conflicts with the current state.")


class BusinessRuleError(AppError):
    code = "error.business_rule"
    status_code = 422
    default_message = _("This action is not allowed by a business rule.")


class ThrottledError(AppError):
    code = "error.throttled"
    status_code = 429
    default_message = _("Too many requests. Please slow down.")


class ServiceUnavailableError(AppError):
    code = "error.service_unavailable"
    status_code = 503
    default_message = _("The service is temporarily unavailable.")


# --- domain-specific ---------------------------------------------------------


class TenantAmbiguousError(ConflictError):
    """The caller belongs to several tenants and did not send ``X-Tenant``."""

    code = "tenant.ambiguous"
    default_message = _("Select which workspace to use with the X-Tenant header.")


class TenantAccessDeniedError(NotFoundError):
    """Deliberately a 404: never confirm that another tenant's object exists."""

    code = "tenant.not_found"
    default_message = _("The requested resource was not found.")


class IdempotencyKeyReusedError(ConflictError):
    code = "idempotency.key_reused"
    default_message = _("This idempotency key was already used with a different request.")


class MaintenanceModeError(ServiceUnavailableError):
    code = "system.maintenance"
    default_message = _("The platform is under maintenance. Please try again shortly.")
