from __future__ import annotations

from apps.features.manifests import FeatureCategory, FeatureManifest, MenuEntry, PreviewStep
from apps.platforms.base import Choice, Reply

APPOINTMENT = FeatureManifest(
    slug="appointment",
    category=FeatureCategory.APPOINTMENT,
    name_key="feature.appointment.name",
    description_key="feature.appointment.description",
    icon="calendar",
    requires=("business_profile", "working_hours"),
    menu=(MenuEntry(label_key="menu.book", route="appointment:book", sort_order=5),),
    price_keys=("feature.appointment.setup", "feature.appointment.monthly"),
    permissions=("appointments.view", "appointments.manage"),
    preview=(
        PreviewStep(
            title_key="preview.step.book_service",
            user_says_key="menu.book",
            reply=Reply(
                text_key="bot.appointment.select_service",
                choices=[
                    Choice(label_key="bot.appointment.sample_service_1", value="service:1"),
                    Choice(label_key="bot.appointment.sample_service_2", value="service:2"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.book_staff",
            reply=Reply(
                text_key="bot.appointment.select_staff",
                choices=[
                    Choice(label_key="bot.appointment.sample_staff_1", value="staff:1"),
                    Choice(label_key="bot.appointment.sample_staff_2", value="staff:2"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.book_slot",
            reply=Reply(
                text_key="bot.appointment.select_slot",
                choices=[
                    Choice(label_key="bot.appointment.sample_slot_1", value="slot:1"),
                    Choice(label_key="bot.appointment.sample_slot_2", value="slot:2"),
                    Choice(label_key="bot.appointment.sample_slot_3", value="slot:3"),
                ],
            ),
        ),
        PreviewStep(
            title_key="preview.step.book_confirm",
            reply=Reply(text_key="bot.appointment.confirmed"),
        ),
    ),
)

APPOINTMENT_REMINDERS = FeatureManifest(
    slug="appointment_reminders",
    category=FeatureCategory.APPOINTMENT,
    name_key="feature.appointment_reminders.name",
    description_key="feature.appointment_reminders.description",
    icon="bell-ring",
    requires=("appointment",),
    price_keys=("feature.appointment_reminders.setup", "feature.appointment_reminders.monthly"),
    preview=(
        PreviewStep(
            title_key="preview.step.reminder",
            reply=Reply(text_key="bot.appointment.reminder"),
        ),
    ),
)

MANIFESTS = (APPOINTMENT, APPOINTMENT_REMINDERS)
