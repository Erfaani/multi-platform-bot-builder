"""Payment admin — the finance review queue (spec §26).

Receipts are attacker-controlled files opened by staff, so downloads go through a view
that checks scope, forces `attachment`, refuses unscanned files, and audit-logs the
access (SECURITY.md §7). The raw file field is never rendered as a link.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from apps.audit.services import record_audit
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentReceipt,
    PaymentStatus,
    ReceiptScanStatus,
)
from apps.payments.services import approve_payment, reject_payment


class RejectForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        help_text="Shown to the customer. Be specific enough that they can fix it.",
    )
    internal_note = forms.CharField(
        max_length=1000, required=False, widget=forms.Textarea, help_text="Staff only."
    )


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "currency", "network", "is_enabled", "sort_order")
    list_filter = ("kind", "currency", "is_enabled")
    search_fields = ("name", "provider_slug")
    list_editable = ("is_enabled", "sort_order")
    readonly_fields = ("public_id",)
    fieldsets = (
        (None, {"fields": ("name", "kind", "provider_slug", "is_enabled", "sort_order")}),
        ("Money", {"fields": ("currency", "network", "minimum_amount_minor")}),
        (
            "Receiving details",
            {
                "fields": ("config", "instructions", "country_scope"),
                "description": (
                    "Our own card number or wallet address. No customer card data is "
                    "ever stored here."
                ),
            },
        ),
    )


class PaymentReceiptInline(admin.TabularInline):
    model = PaymentReceipt
    extra = 0
    readonly_fields = (
        "original_filename",
        "content_type",
        "size_bytes",
        "sha256",
        "scan_status",
        "uploaded_by",
        "uploaded_ip",
        "download_link",
        "created_at",
    )
    fields = readonly_fields
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="File")
    def download_link(self, obj: PaymentReceipt) -> str:
        if obj.scan_status != ReceiptScanStatus.CLEAN:
            return format_html("<i>unavailable ({})</i>", obj.scan_status)
        url = reverse("admin:payments_receipt_download", args=[obj.pk])
        return format_html('<a href="{}" download>Download</a>', url)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "order_number",
        "status",
        "amount_display",
        "payment_method",
        "duplicate_flag",
        "submitted_at",
        "review_actions",
    )
    list_filter = ("status", "payment_method", "currency")
    search_fields = ("public_id", "tx_hash", "order__number", "order__tenant__name")
    readonly_fields = (
        "public_id",
        "order",
        "payment_method",
        "amount_minor",
        "currency",
        "tx_hash",
        "sender_wallet",
        "network",
        "payer_note",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
    )
    inlines = (PaymentReceiptInline,)
    date_hierarchy = "created_at"

    # Status changes go through the service layer so the order moves with the payment.
    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Order", ordering="order__number")
    def order_number(self, obj: Payment) -> str:
        return f"#{obj.order.number}"

    @admin.display(description="Amount")
    def amount_display(self, obj: Payment) -> str:
        from apps.core.formatting import format_money

        return format_money(obj.amount, locale="en")

    @admin.display(description="Flags")
    def duplicate_flag(self, obj: Payment) -> str:
        if "[auto]" in (obj.internal_note or ""):
            return format_html('<b style="color:#b45309">duplicate receipt</b>')
        return ""

    @admin.display(description="Review")
    def review_actions(self, obj: Payment) -> str:
        if obj.status not in {PaymentStatus.RECEIPT_SUBMITTED, PaymentStatus.UNDER_REVIEW}:
            return obj.status
        approve = reverse("admin:payments_payment_approve", args=[obj.pk])
        reject = reverse("admin:payments_payment_reject", args=[obj.pk])
        return format_html(
            '<a href="{}">Approve</a> · <a href="{}">Reject</a>', approve, reject
        )

    def get_urls(self):
        return [
            path(
                "<int:pk>/approve/",
                self.admin_site.admin_view(self.approve_view),
                name="payments_payment_approve",
            ),
            path(
                "<int:pk>/reject/",
                self.admin_site.admin_view(self.reject_view),
                name="payments_payment_reject",
            ),
            path(
                "receipt/<int:pk>/download/",
                self.admin_site.admin_view(self.receipt_download_view),
                name="payments_receipt_download",
            ),
            *super().get_urls(),
        ]

    def approve_view(self, request, pk: int):
        payment = get_object_or_404(Payment, pk=pk)
        if request.method == "POST":
            approve_payment(payment=payment, staff=request.user)
            self.message_user(
                request,
                f"Payment approved. Order #{payment.order.number} is now PAID and will "
                "be provisioned.",
                messages.SUCCESS,
            )
            return redirect(reverse("admin:payments_payment_changelist"))
        return render(
            request,
            "admin/payments/confirm_approve.html",
            {**self.admin_site.each_context(request), "payment": payment, "title": "Approve payment"},
        )

    def reject_view(self, request, pk: int):
        payment = get_object_or_404(Payment, pk=pk)
        if request.method == "POST":
            form = RejectForm(request.POST)
            if form.is_valid():
                reject_payment(
                    payment=payment,
                    staff=request.user,
                    reason=form.cleaned_data["reason"],
                    note=form.cleaned_data.get("internal_note", ""),
                )
                self.message_user(request, "Payment rejected.", messages.WARNING)
                return redirect(reverse("admin:payments_payment_changelist"))
        else:
            form = RejectForm()
        return render(
            request,
            "admin/payments/confirm_reject.html",
            {
                **self.admin_site.each_context(request),
                "payment": payment,
                "form": form,
                "title": "Reject payment",
            },
        )

    def receipt_download_view(self, request, pk: int):
        from apps.accounts.services import has_scope

        if not has_scope(request.user, "payments.review"):
            raise Http404

        receipt = get_object_or_404(PaymentReceipt, pk=pk)
        if receipt.scan_status != ReceiptScanStatus.CLEAN:
            # Never hand an unscanned customer upload to a staff browser.
            raise Http404

        record_audit(
            actor=request.user,
            action="payment.receipt_viewed",
            resource_type="payment_receipt",
            resource_id=str(receipt.pk),
            tenant=receipt.payment.order.tenant,
            ip=request.META.get("REMOTE_ADDR"),
        )

        response = FileResponse(
            receipt.file.open("rb"), as_attachment=True, filename=receipt.file.name.rsplit("/", 1)[-1]
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
