"""Authentication audit trail (SECURITY.md §11)."""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from apps.audit.services import record_audit


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs) -> None:
    ip = _client_ip(request)
    if ip:
        user.last_login_ip = ip
        user.save(update_fields=["last_login_ip"])
    record_audit(
        actor=user,
        action="user.login",
        resource_type="user",
        resource_id=str(user.public_id),
        ip=ip,
        user_agent=(request.META.get("HTTP_USER_AGENT") if request else None),
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs) -> None:
    # Log the attempt, never the submitted password or a confirmation the account exists.
    record_audit(
        actor=None,
        action="user.login_failed",
        resource_type="user",
        resource_id=None,
        ip=_client_ip(request),
        metadata={"email_attempted": bool(credentials.get("username") or credentials.get("email"))},
    )
