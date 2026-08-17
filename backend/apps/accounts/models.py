"""Platform users and staff roles.

A ``User`` is a platform account. The end users of a *customer's* bot are not users
here — they are tenant-scoped ``BusinessContact`` records with no credentials
(ARCHITECTURE.md §7).
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("email_verified_at", timezone.now())
        if extra.get("is_staff") is not True or extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    email = models.EmailField(_("email address"), unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    # Localization preferences (I18N.md §2)
    preferred_locale = models.CharField(max_length=8, default="en")
    preferred_currency = CurrencyCodeField(default="USD")
    country = models.CharField(max_length=2, blank=True, help_text=_("ISO 3166-1 alpha-2"))
    timezone = models.CharField(max_length=64, default="UTC")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False, help_text=_("Access to the Django admin. Platform roles are separate.")
    )
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "user"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


class StaffRole(models.TextChoices):
    """Platform staff roles (spec §55). Distinct from tenant roles."""

    SUPER_ADMIN = "SUPER_ADMIN", _("Super admin")
    ADMIN = "ADMIN", _("Admin")
    SUPPORT_AGENT = "SUPPORT_AGENT", _("Support agent")
    FINANCE_AGENT = "FINANCE_AGENT", _("Finance agent")
    BOT_OPS_AGENT = "BOT_OPS_AGENT", _("Bot operations agent")


#: Scopes granted by each role. Least privilege: support cannot approve payments,
#: finance cannot suspend bots, only super admin reads audit logs.
ROLE_SCOPES: dict[str, set[str]] = {
    StaffRole.SUPER_ADMIN: {"*"},
    StaffRole.ADMIN: {
        "customers.view",
        "orders.view",
        "orders.manage",
        "catalog.manage",
        "pricing.manage",
        "translations.manage",
        "settings.manage",
        "dashboard.view",
    },
    StaffRole.SUPPORT_AGENT: {
        "customers.view",
        "orders.view",
        "support.manage",
        "dashboard.view",
    },
    StaffRole.FINANCE_AGENT: {
        "orders.view",
        "payments.view",
        "payments.review",
        "payment_methods.manage",
        "subscriptions.manage",
        "dashboard.view",
    },
    StaffRole.BOT_OPS_AGENT: {
        "bots.view",
        "bots.manage",
        "provisioning.manage",
        "bot_pool.manage",
        "dashboard.view",
    },
}


class UserStaffRole(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_roles")
    role = models.CharField(max_length=32, choices=StaffRole.choices)
    granted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "user_staff_role"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="user_staff_role_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.user.email}: {self.role}"

    @property
    def scopes(self) -> set[str]:
        return ROLE_SCOPES.get(self.role, set())


class EmailVerificationToken(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "email_verification_token"

    @property
    def is_usable(self) -> bool:
        return self.consumed_at is None and self.expires_at > timezone.now()
