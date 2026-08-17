"""Append-only audit log (SECURITY.md §11).

The application database role should have no UPDATE/DELETE grant on this table in
production — a tamperable audit log is not evidence of anything.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class ActorType(models.TextChoices):
    USER = "USER", _("User")
    STAFF = "STAFF", _("Staff")
    SYSTEM = "SYSTEM", _("System")
    ANONYMOUS = "ANONYMOUS", _("Anonymous")


class AuditLog(models.Model):
    actor_type = models.CharField(max_length=16, choices=ActorType.choices, default=ActorType.SYSTEM)
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_label = models.CharField(
        max_length=255, blank=True, help_text=_("Preserved even if the account is deleted.")
    )
    tenant = models.ForeignKey(
        "customers.Tenant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    action = models.CharField(max_length=128, db_index=True)
    resource_type = models.CharField(max_length=64, blank=True)
    resource_id = models.CharField(max_length=64, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="audit_tenant_time_idx"),
            models.Index(fields=["resource_type", "resource_id"], name="audit_resource_idx"),
            models.Index(fields=["action", "-created_at"], name="audit_action_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_label or self.actor_type}"
