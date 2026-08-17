"""Bot serializers.

There is no field here that exposes a credential, and there never should be. The
security suite scans every response for token-shaped strings to keep it that way.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.bots.models import Bot, BotPlatformInstance
from apps.businesses.models import BusinessProfile, FaqEntry
from apps.core.formatting import money_to_representation
from apps.core.money import Money


class BotInstanceSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    link = serializers.CharField(read_only=True)
    needs_token = serializers.SerializerMethodField()

    class Meta:
        model = BotPlatformInstance
        fields = (
            "id",
            "platform",
            "status",
            "username",
            "display_name",
            "link",
            "acquisition_mode",
            "needs_token",
            "webhook_set_at",
            "last_update_at",
        )
        read_only_fields = fields

    def get_needs_token(self, obj: BotPlatformInstance) -> bool:
        """Whether the customer still has to complete the BotFather handoff."""
        return obj.status == BotPlatformInstance.Status.AWAITING_TOKEN


class BotSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    template = serializers.CharField(source="template.slug", read_only=True)
    instances = BotInstanceSerializer(many=True, read_only=True)
    features = serializers.SerializerMethodField()
    provisioning = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField()

    class Meta:
        model = Bot
        fields = (
            "id",
            "name",
            "status",
            "template",
            "default_locale",
            "timezone",
            "currency",
            "instances",
            "features",
            "provisioning",
            "subscription",
            "last_activity_at",
            "created_at",
        )
        read_only_fields = ("status", "created_at", "last_activity_at")

    def get_features(self, obj: Bot) -> list[str]:
        # `.all()` (not `.filter()`/`.order_by()`) so this reads the `bot_features__feature`
        # prefetch cache from the viewset's queryset instead of issuing a fresh query per
        # bot — any further queryset method here would silently defeat that prefetch.
        enabled = sorted(
            (bf for bf in obj.bot_features.all() if bf.is_enabled),
            key=lambda bf: bf.feature.sort_order,
        )
        return [bf.feature.slug for bf in enabled]

    def get_provisioning(self, obj: Bot) -> dict | None:
        """Live progress, so the dashboard can show real steps rather than a spinner.

        Sorted in Python, over `.all()`, for the same reason as `get_features` above:
        reads the `jobs__steps` prefetch cache rather than re-querying per bot.
        """
        jobs = list(obj.jobs.all())
        if not jobs:
            return None
        job = max(jobs, key=lambda j: j.created_at)
        steps = sorted(job.steps.all(), key=lambda step: step.sequence)
        return {
            "status": job.status,
            "strategy": job.strategy,
            "error_code": job.error_code,
            "steps": [{"slug": step.step_slug, "status": step.status} for step in steps],
        }

    def get_subscription(self, obj: Bot) -> dict | None:
        subscription = getattr(obj, "subscription", None)
        if subscription is None:
            return None
        return {
            "status": subscription.status,
            "monthly_amount": money_to_representation(subscription.monthly_amount),
            "current_period_end": subscription.current_period_end,
            "grace_period_ends_at": subscription.grace_period_ends_at,
        }


class BotConfigurationSerializer(serializers.Serializer):
    """What a customer may change themselves (spec §24)."""

    name = serializers.CharField(max_length=128, required=False)
    welcome_message = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    default_locale = serializers.CharField(max_length=8, required=False)
    timezone = serializers.CharField(max_length=64, required=False)


class SubmitTokenSerializer(serializers.Serializer):
    """Tier B handoff. The token is validated, encrypted, and never echoed back."""

    token = serializers.CharField(max_length=128, trim_whitespace=True, write_only=True)


class BusinessProfileSerializer(serializers.ModelSerializer):
    """What the bot actually says about the business (spec §24)."""

    class Meta:
        model = BusinessProfile
        fields = (
            "display_name",
            "description",
            "phone",
            "secondary_phone",
            "email",
            "website",
            "address",
            "city",
            "working_hours_text",
        )


class BusinessProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    secondary_phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=128, required=False, allow_blank=True)
    working_hours_text = serializers.CharField(max_length=255, required=False, allow_blank=True)


class FaqEntrySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = FaqEntry
        fields = ("id", "question", "answer", "category", "sort_order", "is_active", "source")
        read_only_fields = ("source",)


class FaqEntryCreateSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=255)
    answer = serializers.CharField()
    sort_order = serializers.IntegerField(required=False, default=100)


class FaqEntryUpdateSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=255, required=False)
    answer = serializers.CharField(required=False)
    sort_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)


class AvailableFeatureSerializer(serializers.Serializer):
    """A catalogue feature this bot could add, with its price (spec §24 upsell)."""

    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    setup_amount = serializers.SerializerMethodField()
    monthly_amount = serializers.SerializerMethodField()

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_setup_amount(self, obj: dict) -> dict:
        return money_to_representation(
            Money(obj["setup_amount_minor"], obj["currency"]), locale=self._locale()
        )

    def get_monthly_amount(self, obj: dict) -> dict:
        return money_to_representation(
            Money(obj["monthly_amount_minor"], obj["currency"]), locale=self._locale()
        )


class AddonQuoteRequestSerializer(serializers.Serializer):
    features = serializers.ListField(
        child=serializers.SlugField(), allow_empty=False, max_length=20
    )


class AnalyticsDailyPointSerializer(serializers.Serializer):
    date = serializers.CharField()
    count = serializers.IntegerField()


class AnalyticsSummarySerializer(serializers.Serializer):
    total_contacts = serializers.IntegerField()
    new_contacts_7d = serializers.IntegerField()
    messages_7d = serializers.IntegerField()
    daily_messages = AnalyticsDailyPointSerializer(many=True)


class BroadcastSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)
