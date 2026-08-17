"""Uniform API error responses (API.md §1).

Every failure leaves through here, so clients see one shape and stack traces never do.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core import errors
from apps.core.request_context import get_request_id

logger = logging.getLogger(__name__)

_DRF_CODE_MAP: dict[type, type[errors.AppError]] = {
    drf_exceptions.NotAuthenticated: errors.AuthenticationError,
    drf_exceptions.AuthenticationFailed: errors.AuthenticationError,
    drf_exceptions.PermissionDenied: errors.PermissionDeniedError,
    drf_exceptions.NotFound: errors.NotFoundError,
    drf_exceptions.Throttled: errors.ThrottledError,
    drf_exceptions.MethodNotAllowed: errors.ValidationError,
    drf_exceptions.UnsupportedMediaType: errors.ValidationError,
}


def _build_body(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    field_errors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": str(message),
        "trace_id": get_request_id(),
    }
    if details:
        error["details"] = details
    if field_errors:
        error["field_errors"] = field_errors
    return {"error": error}


def _normalise_field_errors(detail: Any) -> tuple[dict[str, Any], str]:
    """Split DRF's validation detail into per-field errors and a summary message."""
    if isinstance(detail, dict):
        field_errors = {
            key: [str(item) for item in (value if isinstance(value, list) else [value])]
            for key, value in detail.items()
        }
        return field_errors, str(errors.ValidationError.default_message)
    if isinstance(detail, list):
        return {}, "; ".join(str(item) for item in detail)
    return {}, str(detail)


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    request = context.get("request")
    path = getattr(request, "path", "?")

    # --- our own domain errors ---
    if isinstance(exc, errors.AppError):
        if exc.status_code >= 500:
            logger.exception("AppError at %s", path)
        else:
            logger.info("AppError %s at %s", exc.code, path)
        response = Response(
            _build_body(
                exc.code, str(exc.message), details=exc.details, field_errors=exc.field_errors
            ),
            status=exc.status_code,
        )
        if isinstance(exc, errors.ThrottledError) and "retry_after" in exc.details:
            response["Retry-After"] = str(exc.details["retry_after"])
        return response

    # --- Django's own ---
    if isinstance(exc, Http404):
        return Response(
            _build_body(errors.NotFoundError.code, str(errors.NotFoundError.default_message)),
            status=404,
        )
    if isinstance(exc, PermissionDenied):
        return Response(
            _build_body(
                errors.PermissionDeniedError.code,
                str(errors.PermissionDeniedError.default_message),
            ),
            status=403,
        )
    if isinstance(exc, DjangoValidationError):
        return Response(
            _build_body(
                errors.ValidationError.code,
                str(errors.ValidationError.default_message),
                field_errors=getattr(exc, "message_dict", None),
            ),
            status=400,
        )

    # --- DRF ---
    if isinstance(exc, drf_exceptions.ValidationError):
        field_errors, message = _normalise_field_errors(exc.detail)
        return Response(
            _build_body(errors.ValidationError.code, message, field_errors=field_errors),
            status=400,
        )

    for drf_type, app_type in _DRF_CODE_MAP.items():
        if isinstance(exc, drf_type):
            details = {}
            if isinstance(exc, drf_exceptions.Throttled) and exc.wait:
                details["retry_after"] = int(exc.wait)
            response = Response(
                _build_body(app_type.code, str(exc.detail), details=details),
                status=exc.status_code,
            )
            if details:
                response["Retry-After"] = str(details["retry_after"])
            return response

    # Let DRF handle anything else it recognises.
    response = drf_exception_handler(exc, context)
    if response is not None:
        return Response(
            _build_body("error.request_failed", str(response.data)), status=response.status_code
        )

    # Unhandled: log everything, tell the client nothing.
    logger.exception("Unhandled exception at %s", path)
    return Response(
        _build_body("error.internal", str(errors.AppError.default_message)), status=500
    )
