from __future__ import annotations

from rest_framework import serializers


class InitDataSerializer(serializers.Serializer):
    """Every Mini App request carries Telegram's own `initData` string instead of a
    session token — see `apps.miniapp.services.verify_init_data`."""

    init_data = serializers.CharField()


class AppointmentSlotsRequestSerializer(InitDataSerializer):
    service = serializers.IntegerField()
    staff = serializers.IntegerField()
    date = serializers.DateField()


class BookAppointmentRequestSerializer(InitDataSerializer):
    service = serializers.IntegerField()
    staff = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
