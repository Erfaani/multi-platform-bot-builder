"""Subscription admin — manual renewal and suspension (spec's "admin manual management").

Same shape as `apps.payments.admin`'s approve/reject queue: status changes go through the
service layer via a confirm-then-POST view, never a bare Django admin field edit, so the
runtime (webhook removal, `Bot`/`BotPlatformInstance` status) always moves with the record.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from apps.orders.domain.state_machine import Actor
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.subscriptions.services import renew, suspend


class SuspendForm(forms.Form):
    reason = forms.CharField(
        max_length=255, required=False, help_text="Internal note — not shown to the customer."
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "bot", "status", "monthly_amount_display", "current_period_end",
        "grace_period_ends_at", "actions_column",
    )
    list_filter = ("status", "currency")
    search_fields = ("bot__name", "public_id")
    readonly_fields = (
        "public_id", "bot", "monthly_amount_minor", "currency", "suspended_at",
        "last_reminder_days", "created_at", "updated_at",
    )
    date_hierarchy = "current_period_end"

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Monthly amount")
    def monthly_amount_display(self, obj: Subscription) -> str:
        from apps.core.formatting import format_money

        return format_money(obj.monthly_amount, locale="en")

    @admin.display(description="Actions")
    def actions_column(self, obj: Subscription) -> str:
        if obj.status == SubscriptionStatus.ACTIVE:
            suspend_url = reverse("admin:subscriptions_subscription_suspend", args=[obj.pk])
            return format_html('<a href="{}">Suspend</a>', suspend_url)
        renew_url = reverse("admin:subscriptions_subscription_renew", args=[obj.pk])
        return format_html('<a href="{}">Renew</a>', renew_url)

    def get_urls(self):
        return [
            path(
                "<int:pk>/renew/",
                self.admin_site.admin_view(self.renew_view),
                name="subscriptions_subscription_renew",
            ),
            path(
                "<int:pk>/suspend/",
                self.admin_site.admin_view(self.suspend_view),
                name="subscriptions_subscription_suspend",
            ),
            *super().get_urls(),
        ]

    def renew_view(self, request, pk: int):
        subscription = get_object_or_404(Subscription, pk=pk)
        if request.method == "POST":
            renew(subscription=subscription, user=request.user, reason="Renewed by staff")
            self.message_user(
                request, f"Subscription renewed for {subscription.bot}.", messages.SUCCESS
            )
            return redirect(reverse("admin:subscriptions_subscription_changelist"))
        return render(
            request,
            "admin/subscriptions/confirm_renew.html",
            {**self.admin_site.each_context(request), "subscription": subscription, "title": "Renew subscription"},
        )

    def suspend_view(self, request, pk: int):
        subscription = get_object_or_404(Subscription, pk=pk)
        if request.method == "POST":
            form = SuspendForm(request.POST)
            if form.is_valid():
                suspend(
                    subscription=subscription,
                    actor_type="STAFF",
                    user=request.user,
                    reason=form.cleaned_data.get("reason", "") or "Suspended by staff",
                )
                self.message_user(
                    request, f"Subscription suspended for {subscription.bot}.", messages.WARNING
                )
                return redirect(reverse("admin:subscriptions_subscription_changelist"))
        else:
            form = SuspendForm()
        return render(
            request,
            "admin/subscriptions/confirm_suspend.html",
            {
                **self.admin_site.each_context(request),
                "subscription": subscription,
                "form": form,
                "title": "Suspend subscription",
            },
        )
