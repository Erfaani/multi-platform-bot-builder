from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.appointments.api.serializers import (
    AppointmentServiceSerializer,
    SlotSerializer,
    StaffMemberSerializer,
)
from apps.appointments.models import AppointmentService, StaffMember
from apps.bots.api.serializers import BusinessProfileSerializer, FaqEntrySerializer
from apps.bots.models import BotPlatformInstance
from apps.commerce.api.serializers import (
    CourseOfferingSerializer,
    ProductSerializer,
    PropertyListingSerializer,
)
from apps.core.errors import NotFoundError
from apps.miniapp.api.serializers import (
    AppointmentSlotsRequestSerializer,
    BookAppointmentRequestSerializer,
    InitDataSerializer,
)
from apps.miniapp.services import enabled_feature_slugs, upsert_contact, verify_init_data


def _active_instance(instance_public_id: str) -> BotPlatformInstance:
    instance = (
        BotPlatformInstance.objects.select_related("bot__tenant", "bot__configuration")
        .filter(
            public_id=instance_public_id,
            platform="telegram",
            status=BotPlatformInstance.Status.ACTIVE,
            bot__status="ACTIVE",
        )
        .first()
    )
    if instance is None:
        raise NotFoundError()
    return instance


class MiniAppContentView(APIView):
    """Everything the Mini App's home screen needs in one call — which sections to
    show is driven by the bot's own enabled features, exactly like the bot's chat menu
    (`apps.bot_runtime.router.menu_routes_for`), just rendered as a page instead of
    buttons."""

    permission_classes = (permissions.AllowAny,)

    @extend_schema(request=InitDataSerializer, responses={200: None})
    def post(self, request: Request, instance_public_id: str) -> Response:
        instance = _active_instance(instance_public_id)
        serializer = InitDataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verify_init_data(instance=instance, raw_init_data=serializer.validated_data["init_data"])

        bot = instance.bot
        features = enabled_feature_slugs(bot)
        locale = getattr(request, "locale", bot.default_locale)
        ctx = {"locale": locale}

        from apps.businesses import services as business_services

        profile = business_services.get_or_create_profile(bot)
        payload: dict = {
            "bot_name": bot.name,
            "business": BusinessProfileSerializer(profile).data,
        }

        if "faq" in features:
            payload["faq"] = FaqEntrySerializer(business_services.list_faq(bot), many=True).data

        if "product_catalog" in features:
            from apps.commerce import services as commerce_services

            payload["products"] = ProductSerializer(
                commerce_services.list_products(bot.pk), many=True, context=ctx
            ).data

        if "property_listings" in features:
            from apps.commerce import services as commerce_services

            payload["properties"] = PropertyListingSerializer(
                commerce_services.list_properties(bot.pk), many=True, context=ctx
            ).data

        if "course_catalog" in features:
            from apps.commerce import services as commerce_services

            payload["courses"] = CourseOfferingSerializer(
                commerce_services.list_courses(bot.pk), many=True, context=ctx
            ).data

        if "appointment" in features:
            from apps.appointments import services as appointment_services

            payload["appointment_services"] = AppointmentServiceSerializer(
                appointment_services.list_services(bot.pk), many=True, context=ctx
            ).data
            payload["staff"] = StaffMemberSerializer(
                appointment_services.list_staff(bot.pk), many=True
            ).data

        return Response(payload)


class MiniAppAppointmentSlotsView(APIView):
    permission_classes = (permissions.AllowAny,)

    @extend_schema(request=AppointmentSlotsRequestSerializer, responses={200: SlotSerializer(many=True)})
    def post(self, request: Request, instance_public_id: str) -> Response:
        from apps.appointments import services as appointment_services

        instance = _active_instance(instance_public_id)
        serializer = AppointmentSlotsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verify_init_data(instance=instance, raw_init_data=serializer.validated_data["init_data"])

        bot = instance.bot
        data = serializer.validated_data
        service = AppointmentService.objects.filter(bot=bot, pk=data["service"]).first()
        staff = StaffMember.objects.filter(bot=bot, pk=data["staff"]).first()
        if service is None or staff is None:
            raise NotFoundError()

        slots = appointment_services.available_slots(
            bot_id=bot.pk, timezone=bot.timezone, service=service, staff=staff, day=data["date"]
        )
        return Response(
            SlotSerializer(
                [{"starts_at": s.starts_at, "ends_at": s.ends_at} for s in slots], many=True
            ).data
        )


class MiniAppBookAppointmentView(APIView):
    permission_classes = (permissions.AllowAny,)

    @extend_schema(request=BookAppointmentRequestSerializer, responses={201: None})
    def post(self, request: Request, instance_public_id: str) -> Response:
        from apps.appointments import services as appointment_services

        instance = _active_instance(instance_public_id)
        serializer = BookAppointmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        telegram_user = verify_init_data(
            instance=instance, raw_init_data=serializer.validated_data["init_data"]
        )

        bot = instance.bot
        data = serializer.validated_data
        service = AppointmentService.objects.filter(bot=bot, pk=data["service"]).first()
        staff = StaffMember.objects.filter(bot=bot, pk=data["staff"]).first()
        if service is None or staff is None:
            raise NotFoundError()

        contact = upsert_contact(instance=instance, telegram_user=telegram_user)
        appointment = appointment_services.book_appointment(
            bot=bot, contact=contact, service=service, staff=staff, starts_at=data["starts_at"]
        )
        from apps.appointments.api.serializers import AppointmentSerializer

        return Response(AppointmentSerializer(appointment).data, status=201)
