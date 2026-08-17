"""Payments (spec §14–16).

Manual payments only in v1, behind a provider abstraction so Stripe or an Iranian
gateway can be added without touching the order system.

Nothing here stores a *customer's* card details. `PaymentMethod.config` holds the
**platform's own** receiving details — our card number, our wallet address — which an
admin maintains without a deploy (spec §26).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TimeStampedModel
from apps.core.money import MoneyProxy


class PaymentMethodKind(models.TextChoices):
    MANUAL_CARD = "MANUAL_CARD", _("Manual card transfer")
    MANUAL_CRYPTO = "MANUAL_CRYPTO", _("Manual cryptocurrency transfer")
    GATEWAY = "GATEWAY", _("Automated gateway")


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", _("Awaiting payment")
    RECEIPT_SUBMITTED = "RECEIPT_SUBMITTED", _("Receipt submitted")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under review")
    APPROVED = "APPROVED", _("Approved")
    REJECTED = "REJECTED", _("Rejected")


class PaymentMethod(PublicIdModel, TimeStampedModel):
    kind = models.CharField(max_length=24, choices=PaymentMethodKind.choices)
    provider_slug = models.SlugField(
        max_length=64, help_text=_("Which provider implementation handles this method.")
    )
    name = models.CharField(max_length=128)

    currency = CurrencyCodeField()
    network = models.CharField(
        max_length=32, blank=True, help_text=_("TRC20, ERC20, Bitcoin… for crypto methods.")
    )

    #: Receiving details. Card: number, holder, bank. Crypto: wallet address.
    config = models.JSONField(default=dict, blank=True)
    instructions = models.TextField(blank=True)

    minimum_amount_minor = models.BigIntegerField(default=0)
    country_scope = models.JSONField(
        default=list, blank=True, help_text=_("ISO country codes. Empty means anywhere.")
    )

    is_enabled = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    minimum_amount = MoneyProxy("minimum_amount_minor", "currency")

    class Meta:
        db_table = "payment_method"
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.currency})"

    @property
    def requires_transaction_details(self) -> bool:
        return self.kind == PaymentMethodKind.MANUAL_CRYPTO


class Payment(PublicIdModel, TimeStampedModel):
    """One attempt to pay an order.

    An order may accumulate several payments — a rejection is followed by a fresh
    attempt rather than by mutating the rejected record, so the history stays intact.
    """

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, related_name="payments"
    )

    amount_minor = models.BigIntegerField()
    currency = CurrencyCodeField()
    amount = MoneyProxy("amount_minor", "currency")

    status = models.CharField(
        max_length=24, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )

    # Crypto proof (spec §15). Optional for card transfers.
    tx_hash = models.CharField(max_length=128, blank=True, default="")
    sender_wallet = models.CharField(max_length=128, blank=True)
    network = models.CharField(max_length=32, blank=True)
    payer_note = models.CharField(max_length=255, blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rejection_reason = models.CharField(max_length=255, blank=True)
    internal_note = models.TextField(
        blank=True, help_text=_("Staff only. Never shown to the customer.")
    )

    class Meta:
        db_table = "payment"
        ordering = ("-created_at",)
        constraints = [
            # One blockchain transaction cannot settle two orders (SECURITY.md §8).
            # Partial so that blank hashes (card transfers) do not collide.
            models.UniqueConstraint(
                fields=["tx_hash"],
                condition=~models.Q(tx_hash=""),
                name="payment_tx_hash_globally_unique",
            )
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="payment_status_time_idx"),
        ]

    def __str__(self) -> str:
        return f"Payment {self.public_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in {
            PaymentStatus.PENDING,
            PaymentStatus.RECEIPT_SUBMITTED,
            PaymentStatus.UNDER_REVIEW,
        }


class ReceiptScanStatus(models.TextChoices):
    PENDING = "PENDING", _("Not scanned")
    CLEAN = "CLEAN", _("Clean")
    INFECTED = "INFECTED", _("Infected")
    ERROR = "ERROR", _("Scan failed")


class PaymentReceipt(TimeStampedModel):
    """Proof of payment uploaded by a customer.

    Attacker-controlled content that a finance agent will open in a browser, so it is
    stored privately, re-encoded, and never served from a public path (SECURITY.md §7).
    """

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="receipts")

    file = models.FileField(upload_to="receipts/%Y/%m/", max_length=255)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()

    #: Indexed so the same image submitted against several orders is caught
    #: (SECURITY.md §8).
    sha256 = models.CharField(max_length=64, db_index=True)

    scan_status = models.CharField(
        max_length=16, choices=ReceiptScanStatus.choices, default=ReceiptScanStatus.PENDING
    )
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "payment_receipt"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Receipt for {self.payment_id}"
