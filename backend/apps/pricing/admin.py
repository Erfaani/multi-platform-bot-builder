"""Pricing admin.

`PriceVersion` is append-only, so the admin exposes it read-only and offers a
*change price* form instead. Letting a staff member edit an amount in place would
silently rewrite what past customers were quoted (spec §12).
"""

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from apps.pricing.models import BillingKind, PriceList, PriceVersion
from apps.pricing.services import set_price


class ChangePriceForm(forms.Form):
    price_list = forms.ModelChoiceField(queryset=PriceList.objects.filter(is_active=True))
    price_key = forms.CharField(max_length=128)
    amount_minor = forms.IntegerField(
        min_value=0,
        help_text="In minor units: USD cents, IRR rials (exponent 0).",
    )
    billing_kind = forms.ChoiceField(choices=BillingKind.choices)
    note = forms.CharField(max_length=255, required=False)


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ("slug", "currency", "is_default", "is_active", "live_price_count")
    list_filter = ("currency", "is_active", "is_default")
    search_fields = ("slug", "name")
    readonly_fields = ("public_id",)

    @admin.display(description="Live prices")
    def live_price_count(self, obj: PriceList) -> int:
        return obj.versions.filter(valid_to__isnull=True).count()


@admin.register(PriceVersion)
class PriceVersionAdmin(admin.ModelAdmin):
    list_display = (
        "price_key",
        "price_list",
        "amount_minor",
        "billing_kind",
        "state",
        "valid_from",
        "valid_to",
    )
    list_filter = ("price_list", "billing_kind")
    search_fields = ("price_key", "note")
    date_hierarchy = "valid_from"

    # Append-only: history must not be editable from the admin.
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="State")
    def state(self, obj: PriceVersion) -> str:
        if obj.valid_to is None:
            return format_html('<b style="color:#16a34a">live</b>')
        return "closed"

    def get_urls(self):
        return [
            path(
                "change-price/",
                self.admin_site.admin_view(self.change_price_view),
                name="pricing_change_price",
            ),
            *super().get_urls(),
        ]

    def change_price_view(self, request):
        if request.method == "POST":
            form = ChangePriceForm(request.POST)
            if form.is_valid():
                version = set_price(
                    price_list=form.cleaned_data["price_list"],
                    price_key=form.cleaned_data["price_key"],
                    amount_minor=form.cleaned_data["amount_minor"],
                    billing_kind=form.cleaned_data["billing_kind"],
                    actor=request.user,
                    note=form.cleaned_data.get("note", ""),
                )
                self.message_user(
                    request,
                    f"New live price for {version.price_key}. Existing quotes and orders "
                    "keep the amount they were sold at.",
                    messages.SUCCESS,
                )
                return redirect(reverse("admin:pricing_priceversion_changelist"))
        else:
            form = ChangePriceForm()

        return render(
            request,
            "admin/pricing/change_price.html",
            {**self.admin_site.each_context(request), "form": form, "title": "Change a price"},
        )
