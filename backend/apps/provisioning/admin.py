"""Provisioning admin — the operator's answer to "why is this order stuck?" (spec §40)."""

from __future__ import annotations

from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from apps.provisioning.models import JobStatus, ProvisioningJob, ProvisioningStep, StepStatus
from apps.provisioning.saga import compensate, run_job


class StepInline(admin.TabularInline):
    model = ProvisioningStep
    extra = 0
    readonly_fields = (
        "sequence",
        "step_slug",
        "status",
        "attempt",
        "output",
        "error",
        "started_at",
        "finished_at",
    )
    fields = readonly_fields
    ordering = ("sequence",)
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ProvisioningJob)
class ProvisioningJobAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "order_number",
        "strategy",
        "status_badge",
        "progress",
        "error_code",
        "actions_column",
    )
    list_filter = ("status", "strategy")
    search_fields = ("public_id", "order__number", "order__tenant__name", "error_code")
    readonly_fields = (
        "public_id",
        "order",
        "bot",
        "strategy",
        "status",
        "attempt",
        "idempotency_key",
        "error_code",
        "error_detail",
        "started_at",
        "finished_at",
    )
    inlines = (StepInline,)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    @admin.display(description="Order", ordering="order__number")
    def order_number(self, obj: ProvisioningJob) -> str:
        return f"#{obj.order.number}"

    @admin.display(description="Status")
    def status_badge(self, obj: ProvisioningJob) -> str:
        colours = {
            JobStatus.SUCCEEDED: "#16a34a",
            JobStatus.FAILED: "#dc2626",
            JobStatus.AWAITING_CUSTOMER: "#b45309",
        }
        colour = colours.get(obj.status, "#2563eb")
        label = obj.get_status_display()
        return format_html('<b style="color:{}">{}</b>', colour, label)

    @admin.display(description="Progress")
    def progress(self, obj: ProvisioningJob) -> str:
        done = obj.steps.filter(status=StepStatus.SUCCEEDED).count()
        total = obj.steps.count()
        return f"{done}/{total}"

    @admin.display(description="Actions")
    def actions_column(self, obj: ProvisioningJob) -> str:
        if not obj.is_resumable:
            return "—"
        retry = reverse("admin:provisioning_job_retry", args=[obj.pk])
        release = reverse("admin:provisioning_job_compensate", args=[obj.pk])
        return format_html(
            '<a href="{}">Retry</a> · <a href="{}">Release pool entry</a>', retry, release
        )

    def get_urls(self):
        return [
            path(
                "<int:pk>/retry/",
                self.admin_site.admin_view(self.retry_view),
                name="provisioning_job_retry",
            ),
            path(
                "<int:pk>/compensate/",
                self.admin_site.admin_view(self.compensate_view),
                name="provisioning_job_compensate",
            ),
            *super().get_urls(),
        ]

    def retry_view(self, request, pk: int):
        job = get_object_or_404(ProvisioningJob, pk=pk)
        job = run_job(job)
        level = messages.SUCCESS if job.status == JobStatus.SUCCEEDED else messages.WARNING
        self.message_user(
            request,
            f"Job {job.public_id} finished as {job.status}. "
            "Steps that had already succeeded were skipped, not replayed.",
            level,
        )
        return redirect(reverse("admin:provisioning_provisioningjob_changelist"))

    def compensate_view(self, request, pk: int):
        job = compensate(get_object_or_404(ProvisioningJob, pk=pk))
        self.message_user(
            request,
            f"Released reserved resources for job {job.public_id}; any pool entry is "
            "back in stock.",
            messages.SUCCESS,
        )
        return redirect(reverse("admin:provisioning_provisioningjob_changelist"))
