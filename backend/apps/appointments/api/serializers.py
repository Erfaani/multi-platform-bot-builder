from __future__ import annotations

from rest_framework import serializers

from apps.appointments.models import Appointment, AppointmentService, StaffMember
from apps.core.formatting import money_to_representation
from apps.core.money import Money


class AppointmentServiceSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    price = serializers.SerializerMethodField()

    class Meta:
        model = AppointmentService
        fields = (
            "id", "name", "description", "duration_minutes", "buffer_minutes",
            "price_minor", "currency", "price", "is_active", "sort_order",
        )
        extra_kwargs = {"price_minor": {"write_only": True}, "currency": {"write_only": True}}

    def get_price(self, obj: AppointmentService) -> dict | None:
        if not obj.currency:
            return None
        return money_to_representation(
            Money(obj.price_minor, obj.currency), locale=self.context.get("locale", "en")
        )


class AppointmentServiceWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    duration_minutes = serializers.IntegerField(required=False, min_value=1)
    buffer_minutes = serializers.IntegerField(required=False, min_value=0)
    price_minor = serializers.IntegerField(required=False, min_value=0)
    currency = serializers.CharField(max_length=8, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class StaffMemberSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    service_ids = serializers.PrimaryKeyRelatedField(
        source="services", many=True, read_only=True
    )

    class Meta:
        model = StaffMember
        fields = ("id", "name", "service_ids", "is_active", "sort_order")


class StaffMemberWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    service_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class AppointmentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    service = serializers.CharField(source="service.name", read_only=True)
    staff = serializers.CharField(source="staff.name", read_only=True)
    contact_name = serializers.CharField(source="contact.display_name", read_only=True)

    class Meta:
        model = Appointment
        fields = (
            "id", "service", "staff", "contact_name", "starts_at", "ends_at",
            "business_timezone", "status", "cancellation_reason", "created_at",
        )
        read_only_fields = fields


class CancelAppointmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class AvailableSlotsRequestSerializer(serializers.Serializer):
    service = serializers.IntegerField()
    staff = serializers.IntegerField()
    date = serializers.DateField()


class SlotSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
