"""Bot and pool administration.

`BotCredential` is deliberately **not registered**. There is no view, anywhere, that
displays a bot token — an admin screen showing one would defeat the encryption it sits
behind (SECURITY.md §5). Pool stock is added through a form that encrypts on the way in.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from apps.bots.credentials import add_pool_entry, pool_depth
from apps.bots.models import (
    Bot,
    BotConfiguration,
    BotFeature,
    BotPlatformInstance,
    BotPoolEntry,
    WebhookSecret,
)
from apps.core.errors import AppError
from apps.platforms.constants import SELLABLE_PLATFORMS


class AddPoolEntryForm(forms.Form):
    """Register a bot created in Telegram's BotFather or Bale's equivalent."""

    platform = forms.ChoiceField(choices=[(p, p.title()) for p in SELLABLE_PLATFORMS])
    username = forms.CharField(
        max_length=64,
        help_text="Without the @. Fixed at creation time and cannot be changed later.",
    )
    token = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        help_text="Encrypted immediately. It is never displayed again, to anyone.",
    )
    note = forms.CharField(max_length=255, required=False)


class ProbeBaleForm(forms.Form):
    """Runs the BALE.md §2 capability spike against a real bot."""

    token = forms.CharField(
        label="Bale bot token",
        widget=forms.PasswordInput(render_value=False),
        help_text=(
            "Used for this probe only — not stored unless you also register the bot above."
        ),
    )
    chat_id = forms.CharField(
        required=False,
        help_text=(
            "A chat the bot can message. Without it, the messaging questions cannot be "
            "answered."
        ),
    )
    webhook_url = forms.CharField(
        required=False, help_text="A public HTTPS URL, to test setWebhook. Optional."
    )
    apply_results = forms.BooleanField(
        required=False,
        label="Apply results",
        help_text="Record the measured capabilities and update what may be sold on Bale.",
    )


class InstanceInline(admin.TabularInline):
    model = BotPlatformInstance
    extra = 0
    readonly_fields = (
        "platform",
        "status",
        "username",
        "platform_bot_id",
        "acquisition_mode",
        "webhook_set_at",
        "last_update_at",
        "last_send_at",
    )
    fields = readonly_fields
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class BotFeatureInline(admin.TabularInline):
    model = BotFeature
    extra = 0
    autocomplete_fields = ("feature",)


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "status", "platforms", "error_count", "last_activity_at")
    list_filter = ("status", "template")
    search_fields = ("name", "public_id", "tenant__name")
    readonly_fields = ("public_id", "origin_order", "template", "error_count")
    inlines = (InstanceInline, BotFeatureInline)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    @admin.display(description="Channels")
    def platforms(self, obj: Bot) -> str:
        return ", ".join(obj.instances.values_list("platform", flat=True)) or "—"


@admin.register(BotPlatformInstance)
class BotPlatformInstanceAdmin(admin.ModelAdmin):
    list_display = ("username", "platform", "bot", "status", "webhook_set_at", "last_update_at")
    list_filter = ("platform", "status")
    search_fields = ("username", "platform_bot_id", "bot__name")
    readonly_fields = ("public_id", "platform_bot_id", "webhook_url", "webhook_set_at")

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(BotPoolEntry)
class BotPoolEntryAdmin(admin.ModelAdmin):
    """Stock management for the Instant tier (ADR-0002 tier A)."""

    list_display = ("username", "platform", "status", "assigned_instance", "created_at")
    list_filter = ("platform", "status")
    search_fields = ("username", "platform_bot_id", "note")
    readonly_fields = ("public_id", "fingerprint", "assigned_instance", "platform_bot_id")
    exclude = ("ciphertext", "kek_version")

    def has_add_permission(self, request) -> bool:
        # Adding must go through the form that encrypts the token.
        return False

    def changelist_view(self, request, extra_context=None):
        depths = {platform: pool_depth(platform) for platform in SELLABLE_PLATFORMS}
        extra_context = {
            **(extra_context or {}),
            "pool_depths": depths,
            "add_url": reverse("admin:bots_pool_add"),
            "console_url": reverse("admin:bots_platform_console"),
        }
        return super().changelist_view(request, extra_context)

    def get_urls(self):
        return [
            path(
                "stock/",
                self.admin_site.admin_view(self.add_stock_view),
                name="bots_pool_add",
            ),
            path(
                "platform-console/",
                self.admin_site.admin_view(self.console_view),
                name="bots_platform_console",
            ),
            path(
                "probe-bale/",
                self.admin_site.admin_view(self.probe_bale_view),
                name="bots_probe_bale",
            ),
            *super().get_urls(),
        ]

    # -- operator console -------------------------------------------------
    def console_view(self, request):
        """Channel overview: pool depth and whether capabilities are measured."""
        from apps.core.models import SystemSetting
        from apps.platforms.registry import capabilities_for

        platforms = [
            {
                "slug": slug,
                "verified": capabilities_for(slug).verified,
                "pool_depth": pool_depth(slug),
                "capabilities": capabilities_for(slug),
            }
            for slug in SELLABLE_PLATFORMS
        ]
        measured = SystemSetting.objects.filter(key="bale_measured_capabilities").first()

        return render(
            request,
            "admin/platforms/console.html",
            {
                **self.admin_site.each_context(request),
                "title": "Platform operations",
                "platforms": platforms,
                "measured": measured.value if measured else None,
                "probe_url": reverse("admin:bots_probe_bale"),
                "register_url": reverse("admin:bots_pool_add"),
            },
        )

    def probe_bale_view(self, request):
        """Run the BALE.md §2 capability spike from the browser.

        Exists so whoever holds a Bale token can close R-02 without shell access on a
        server — the gate on selling Bale features should not require SSH.
        """
        from apps.platforms.probe import apply_result, probe_bale

        result = None
        if request.method == "POST":
            form = ProbeBaleForm(request.POST)
            if form.is_valid():
                result = probe_bale(
                    token=form.cleaned_data["token"],
                    chat_id=form.cleaned_data.get("chat_id", ""),
                    webhook_url=form.cleaned_data.get("webhook_url", ""),
                )
                if not result.reachable:
                    self.message_user(
                        request,
                        "Could not reach Bale, or the token was rejected. If this is a "
                        "network failure it answers spike question 11: worker-bale needs "
                        "an egress route that can reach Bale.",
                        messages.ERROR,
                    )
                elif form.cleaned_data.get("apply_results"):
                    updated = apply_result(result, actor=request.user)
                    self.message_user(
                        request,
                        f"Applied measured capabilities to {updated} features. Paste the "
                        "values into BALE_CAPABILITIES and set verified=True to finish.",
                        messages.SUCCESS,
                    )
        else:
            form = ProbeBaleForm()

        return render(
            request,
            "admin/platforms/probe_bale.html",
            {
                **self.admin_site.each_context(request),
                "title": "Bale capability probe",
                "form": form,
                "result": result,
            },
        )

    def add_stock_view(self, request):
        if request.method == "POST":
            form = AddPoolEntryForm(request.POST)
            if form.is_valid():
                try:
                    entry = add_pool_entry(
                        platform=form.cleaned_data["platform"],
                        username=form.cleaned_data["username"],
                        token=form.cleaned_data["token"],
                        note=form.cleaned_data.get("note", ""),
                        actor=request.user,
                    )
                except AppError as exc:
                    self.message_user(request, str(exc.message), messages.ERROR)
                else:
                    self.message_user(
                        request, f"Added @{entry.username} to the pool.", messages.SUCCESS
                    )
                    return redirect(reverse("admin:bots_botpoolentry_changelist"))
        else:
            form = AddPoolEntryForm()

        return render(
            request,
            "admin/bots/add_pool_entry.html",
            {**self.admin_site.each_context(request), "form": form, "title": "Add a bot to the pool"},
        )


@admin.register(BotConfiguration)
class BotConfigurationAdmin(admin.ModelAdmin):
    list_display = ("bot", "version", "updated_at")
    search_fields = ("bot__name",)
    readonly_fields = ("version",)


@admin.register(WebhookSecret)
class WebhookSecretAdmin(admin.ModelAdmin):
    list_display = ("instance", "is_active", "valid_from", "valid_to")
    list_filter = ("is_active",)
    readonly_fields = ("secret_hash",)

    def has_add_permission(self, request) -> bool:
        return False

    @admin.display(description="Secret")
    def masked(self, obj) -> str:
        return format_html("<i>stored as a hash</i>")
