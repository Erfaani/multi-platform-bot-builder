from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.ai import services as ai_services
from apps.ai.api.serializers import (
    AiConfigurationSerializer,
    AiConfigurationUpdateSerializer,
    AiUsageRecordSerializer,
    AiUsageSummarySerializer,
    KnowledgeDocumentCreateSerializer,
    KnowledgeDocumentSerializer,
)
from apps.appointments import services as appointment_services
from apps.appointments.api.serializers import (
    AppointmentSerializer,
    AppointmentServiceSerializer,
    AppointmentServiceWriteSerializer,
    AvailableSlotsRequestSerializer,
    CancelAppointmentSerializer,
    RescheduleAppointmentSerializer,
    SlotSerializer,
    StaffMemberSerializer,
    StaffMemberWriteSerializer,
)
from apps.appointments.models import Appointment, AppointmentService, StaffMember
from apps.bots.api.serializers import (
    AddonQuoteRequestSerializer,
    AnalyticsSummarySerializer,
    AvailableFeatureSerializer,
    BotConfigurationSerializer,
    BotSerializer,
    BroadcastSerializer,
    BusinessProfileSerializer,
    BusinessProfileUpdateSerializer,
    FaqEntryCreateSerializer,
    FaqEntrySerializer,
    FaqEntryUpdateSerializer,
    InputRestrictionPolicySerializer,
    InputRestrictionPolicyWriteSerializer,
    SubmitTokenSerializer,
    WorkingHoursWriteSerializer,
)
from apps.bots.models import Bot, BotPlatformInstance
from apps.bots.services import (
    available_addon_features,
    rotate_webhook,
    submit_customer_token,
    update_configuration,
    update_input_restrictions,
)
from apps.businesses import services as business_services
from apps.commerce import services as commerce_services
from apps.commerce.api.serializers import (
    BusinessOrderSerializer,
    CourseOfferingSerializer,
    CourseOfferingWriteSerializer,
    ImageUploadSerializer,
    ProductCategorySerializer,
    ProductCategoryWriteSerializer,
    ProductImageSerializer,
    ProductSerializer,
    ProductWriteSerializer,
    PropertyImageSerializer,
    PropertyListingSerializer,
    PropertyListingWriteSerializer,
    TableReservationSerializer,
)
from apps.core.api.viewsets import TenantScopedReadOnlyViewSet
from apps.core.errors import NotFoundError
from apps.crm import services as crm_services
from apps.crm.api.serializers import (
    AddNoteSerializer,
    FeedbackSerializer,
    LeadSerializer,
    LeadUpdateSerializer,
    TagLeadSerializer,
)


class BotViewSet(TenantScopedReadOnlyViewSet):
    """A customer's bots.

    Read-only plus explicit actions: `status` moves only through provisioning, and a
    credential is never readable at all.
    """

    serializer_class = BotSerializer
    permission_classes = (permissions.IsAuthenticated,)
    queryset = (
        Bot.objects.select_related("template", "configuration", "tenant", "subscription")
        .prefetch_related("instances", "bot_features__feature", "jobs__steps")
        .exclude(status="ARCHIVED")
    )

    def get_serializer_context(self) -> dict:
        return {**super().get_serializer_context(), "locale": getattr(self.request, "locale", "en")}

    @extend_schema(request=BotConfigurationSerializer, responses=BotSerializer)
    @action(detail=True, methods=["patch"], url_path="configuration")
    def configuration(self, request: Request, public_id: str) -> Response:
        serializer = BotConfigurationSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        bot = update_configuration(
            bot=self.get_object(), actor=request.user, **serializer.validated_data
        )
        return Response(BotSerializer(bot).data)

    @extend_schema(request=SubmitTokenSerializer, responses=BotSerializer)
    @action(detail=True, methods=["post"], url_path=r"instances/(?P<instance_id>[^/.]+)/token")
    def submit_token(self, request: Request, public_id: str, instance_id: str) -> Response:
        """Complete the guided BotFather handoff for one channel (ADR-0002 tier B)."""
        bot = self.get_object()
        instance = BotPlatformInstance.objects.filter(
            bot=bot, public_id=instance_id
        ).first()
        if instance is None:
            raise NotFoundError()

        serializer = SubmitTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        submit_customer_token(
            instance=instance, token=serializer.validated_data["token"], user=request.user
        )
        bot.refresh_from_db()
        return Response(BotSerializer(bot).data)

    @extend_schema(request=None, responses=BotSerializer)
    @action(detail=True, methods=["post"], url_path=r"instances/(?P<instance_id>[^/.]+)/rotate-webhook")
    def rotate_instance_webhook(self, request: Request, public_id: str, instance_id: str) -> Response:
        """Customer-triggered: re-register the webhook with a fresh secret."""
        bot = self.get_object()
        instance = BotPlatformInstance.objects.filter(bot=bot, public_id=instance_id).first()
        if instance is None:
            raise NotFoundError()

        rotate_webhook(instance=instance, actor=request.user)
        bot.refresh_from_db()
        return Response(BotSerializer(bot).data)

    # -- business profile (spec §24) --------------------------------------
    @extend_schema(
        request=BusinessProfileUpdateSerializer,
        responses={200: BusinessProfileSerializer},
    )
    @action(detail=True, methods=["get", "patch"], url_path="business-profile")
    def business_profile(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            profile = business_services.get_or_create_profile(bot)
            return Response(BusinessProfileSerializer(profile).data)

        serializer = BusinessProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = business_services.update_business_profile(
            bot=bot, actor=request.user, **serializer.validated_data
        )
        return Response(BusinessProfileSerializer(profile).data)

    @extend_schema(request=ImageUploadSerializer, responses=BusinessProfileSerializer)
    @action(detail=True, methods=["post"], url_path="business-profile/logo")
    def business_profile_logo(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = business_services.set_business_logo(
            bot=bot, actor=request.user, upload=serializer.validated_data["file"]
        )
        return Response(BusinessProfileSerializer(profile).data)

    # -- working hours (spec §24) --------------------------------------------
    @extend_schema(request=WorkingHoursWriteSerializer, responses={200: WorkingHoursWriteSerializer})
    @action(detail=True, methods=["get", "put"], url_path="working-hours")
    def working_hours(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            rows = business_services.list_working_hours(bot.pk)
            return Response(WorkingHoursWriteSerializer({"days": rows}).data)

        serializer = WorkingHoursWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = business_services.set_working_hours(
            bot=bot, actor=request.user, days=serializer.validated_data["days"]
        )
        return Response(WorkingHoursWriteSerializer({"days": rows}).data)

    # -- input restrictions (spec §24, configurable validation) ---------------
    @extend_schema(
        request=InputRestrictionPolicyWriteSerializer, responses={200: InputRestrictionPolicySerializer}
    )
    @action(detail=True, methods=["get", "patch"], url_path="input-restrictions")
    def input_restrictions(self, request: Request, public_id: str) -> Response:
        from apps.bots.services import get_input_restrictions

        bot = self.get_object()

        if request.method == "GET":
            policy = get_input_restrictions(bot.pk)
            return Response(InputRestrictionPolicySerializer(policy).data)

        serializer = InputRestrictionPolicyWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        policy = update_input_restrictions(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(InputRestrictionPolicySerializer(policy).data)

    # -- FAQ ----------------------------------------------------------------
    @extend_schema(
        request=FaqEntryCreateSerializer, responses={200: FaqEntrySerializer(many=True)}
    )
    @action(detail=True, methods=["get", "post"], url_path="faq")
    def faq(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            entries = business_services.list_faq(bot)
            return Response(FaqEntrySerializer(entries, many=True).data)

        serializer = FaqEntryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = business_services.create_faq_entry(
            bot=bot, actor=request.user, **serializer.validated_data
        )
        return Response(FaqEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=FaqEntryUpdateSerializer, responses=FaqEntrySerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"faq/(?P<faq_id>\d+)")
    def faq_detail(self, request: Request, public_id: str, faq_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            business_services.delete_faq_entry(bot=bot, entry_id=int(faq_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = FaqEntryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        entry = business_services.update_faq_entry(
            bot=bot, entry_id=int(faq_id), actor=request.user, **serializer.validated_data
        )
        return Response(FaqEntrySerializer(entry).data)

    # -- add-on features (spec §24 "add features later") --------------------
    @extend_schema(responses=AvailableFeatureSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="available-features")
    def available_features(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        results = available_addon_features(bot, locale=getattr(request, "locale", "en"))
        return Response(
            AvailableFeatureSerializer(
                results, many=True, context=self.get_serializer_context()
            ).data
        )

    @extend_schema(request=AddonQuoteRequestSerializer, responses={201: None})
    @action(detail=True, methods=["post"], url_path="addon-quotes")
    def addon_quote(self, request: Request, public_id: str) -> Response:
        """Price additional features. Returns a quote ready to place as an order.

        Unlike the builder, this quote is never anonymous — it belongs to the bot's
        tenant from the moment it is created, so the client goes straight to
        `POST /orders/` with the returned id, skipping the claim step entirely.
        """
        from apps.orders.api.serializers import QuoteSerializer
        from apps.orders.services import build_addon_quote

        bot = self.get_object()
        serializer = AddonQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quote, auto_added = build_addon_quote(
            bot=bot,
            feature_slugs=serializer.validated_data["features"],
            user=request.user,
            locale=getattr(request, "locale", "en"),
        )
        payload = QuoteSerializer(quote, context=self.get_serializer_context()).data
        payload["auto_added_features"] = auto_added
        return Response(payload, status=status.HTTP_201_CREATED)

    # -- analytics (spec §31) ------------------------------------------------
    @extend_schema(responses=AnalyticsSummarySerializer)
    @action(detail=True, methods=["get"], url_path="analytics")
    def analytics(self, request: Request, public_id: str) -> Response:
        from apps.analytics.services import bot_summary

        summary = bot_summary(self.get_object())
        return Response(AnalyticsSummarySerializer(summary).data)

    # -- appointments: services ----------------------------------------------
    @extend_schema(
        request=AppointmentServiceWriteSerializer,
        responses={200: AppointmentServiceSerializer(many=True)},
    )
    @action(detail=True, methods=["get", "post"], url_path="appointment-services")
    def appointment_services(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            services = appointment_services.list_services(bot.pk)
            return Response(
                AppointmentServiceSerializer(services, many=True, context=self.get_serializer_context()).data
            )

        serializer = AppointmentServiceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = appointment_services.create_service(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(
            AppointmentServiceSerializer(created, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=AppointmentServiceWriteSerializer, responses=AppointmentServiceSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"appointment-services/(?P<service_id>\d+)")
    def appointment_service_detail(self, request: Request, public_id: str, service_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            appointment_services.delete_service(bot=bot, service_id=int(service_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = AppointmentServiceWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = appointment_services.update_service(
            bot=bot, service_id=int(service_id), actor=request.user, **serializer.validated_data
        )
        return Response(AppointmentServiceSerializer(updated, context=self.get_serializer_context()).data)

    # -- appointments: staff --------------------------------------------------
    @extend_schema(request=StaffMemberWriteSerializer, responses={200: StaffMemberSerializer(many=True)})
    @action(detail=True, methods=["get", "post"], url_path="staff")
    def staff(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            rows = appointment_services.list_staff(bot.pk)
            return Response(StaffMemberSerializer(rows, many=True).data)

        serializer = StaffMemberWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = appointment_services.create_staff(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(StaffMemberSerializer(created).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=StaffMemberWriteSerializer, responses=StaffMemberSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"staff/(?P<staff_id>\d+)")
    def staff_detail(self, request: Request, public_id: str, staff_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            appointment_services.delete_staff(bot=bot, staff_id=int(staff_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = StaffMemberWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = appointment_services.update_staff(
            bot=bot, staff_id=int(staff_id), actor=request.user, **serializer.validated_data
        )
        return Response(StaffMemberSerializer(updated).data)

    # -- appointments: availability & the calendar itself ---------------------
    @extend_schema(request=AvailableSlotsRequestSerializer, responses={200: SlotSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="appointment-slots")
    def appointment_slots(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        serializer = AvailableSlotsRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        service = AppointmentService.objects.filter(bot=bot, pk=data["service"]).first()
        staff = StaffMember.objects.filter(bot=bot, pk=data["staff"]).first()
        if service is None or staff is None:
            raise NotFoundError()

        slots = appointment_services.available_slots(
            bot_id=bot.pk, timezone=bot.timezone, service=service, staff=staff, day=data["date"]
        )
        return Response(SlotSerializer([{"starts_at": s.starts_at, "ends_at": s.ends_at} for s in slots], many=True).data)

    @extend_schema(responses={200: AppointmentSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="appointments")
    def appointments(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        rows = appointment_services.list_appointments(bot)
        return Response(AppointmentSerializer(rows, many=True).data)

    @extend_schema(request=CancelAppointmentSerializer, responses=AppointmentSerializer)
    @action(detail=True, methods=["post"], url_path=r"appointments/(?P<appointment_id>[^/.]+)/cancel")
    def cancel_appointment(self, request: Request, public_id: str, appointment_id: str) -> Response:
        bot = self.get_object()
        appointment = Appointment.objects.filter(bot=bot, public_id=appointment_id).first()
        if appointment is None:
            raise NotFoundError()

        serializer = CancelAppointmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cancelled = appointment_services.cancel_appointment(
            appointment=appointment, actor=request.user, reason=serializer.validated_data["reason"]
        )
        return Response(AppointmentSerializer(cancelled).data)

    @extend_schema(request=RescheduleAppointmentSerializer, responses=AppointmentSerializer)
    @action(detail=True, methods=["post"], url_path=r"appointments/(?P<appointment_id>[^/.]+)/reschedule")
    def reschedule_appointment(self, request: Request, public_id: str, appointment_id: str) -> Response:
        bot = self.get_object()
        appointment = Appointment.objects.filter(bot=bot, public_id=appointment_id).first()
        if appointment is None:
            raise NotFoundError()

        serializer = RescheduleAppointmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rescheduled = appointment_services.reschedule_appointment(
            appointment=appointment, actor=request.user, starts_at=serializer.validated_data["starts_at"]
        )
        return Response(AppointmentSerializer(rescheduled).data)

    # -- customer broadcast (spec's notifications module) ---------------------
    @extend_schema(request=BroadcastSerializer, responses={200: None})
    @action(detail=True, methods=["post"], url_path="broadcast")
    def broadcast(self, request: Request, public_id: str) -> Response:
        from apps.notifications.broadcast import send_broadcast

        bot = self.get_object()
        serializer = BroadcastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        recipients = send_broadcast(bot=bot, actor=request.user, text=serializer.validated_data["text"])
        return Response({"recipients": recipients})

    # -- crm: leads -------------------------------------------------------------
    @extend_schema(responses=LeadSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="leads")
    def leads(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        return Response(LeadSerializer(crm_services.list_leads(bot), many=True).data)

    @extend_schema(request=LeadUpdateSerializer, responses=LeadSerializer)
    @action(detail=True, methods=["patch"], url_path=r"leads/(?P<lead_id>[^/.]+)")
    def lead_detail(self, request: Request, public_id: str, lead_id: str) -> Response:
        bot = self.get_object()
        serializer = LeadUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        lead = crm_services.update_lead(
            bot=bot, lead_id=lead_id, actor=request.user, **serializer.validated_data
        )
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=AddNoteSerializer, responses=LeadSerializer)
    @action(detail=True, methods=["post"], url_path=r"leads/(?P<lead_id>[^/.]+)/notes")
    def lead_notes(self, request: Request, public_id: str, lead_id: str) -> Response:
        bot = self.get_object()
        serializer = AddNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crm_services.add_note(
            bot=bot, lead_id=lead_id, actor=request.user, body=serializer.validated_data["body"]
        )
        lead = crm_services.get_lead_for_bot(bot=bot, lead_id=lead_id)
        return Response(LeadSerializer(lead).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=TagLeadSerializer, responses=LeadSerializer)
    @action(detail=True, methods=["post"], url_path=r"leads/(?P<lead_id>[^/.]+)/tags")
    def lead_tags(self, request: Request, public_id: str, lead_id: str) -> Response:
        bot = self.get_object()
        serializer = TagLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crm_services.tag_lead(
            bot=bot, lead_id=lead_id, actor=request.user, tag_name=serializer.validated_data["tag"]
        )
        lead = crm_services.get_lead_for_bot(bot=bot, lead_id=lead_id)
        return Response(LeadSerializer(lead).data, status=status.HTTP_201_CREATED)

    # -- crm: feedback ------------------------------------------------------------
    @extend_schema(responses=FeedbackSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="feedback")
    def feedback(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        return Response(FeedbackSerializer(crm_services.list_feedback(bot), many=True).data)

    # -- commerce: catalogue ------------------------------------------------------
    @extend_schema(request=ProductCategoryWriteSerializer, responses={200: ProductCategorySerializer(many=True)})
    @action(detail=True, methods=["get", "post"], url_path="product-categories")
    def product_categories(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            return Response(ProductCategorySerializer(commerce_services.list_categories(bot.pk), many=True).data)

        serializer = ProductCategoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = commerce_services.create_category(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(ProductCategorySerializer(created).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ProductCategoryWriteSerializer, responses=ProductCategorySerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"product-categories/(?P<category_id>\d+)")
    def product_category_detail(self, request: Request, public_id: str, category_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            commerce_services.delete_category(bot=bot, category_id=int(category_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = ProductCategoryWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = commerce_services.update_category(
            bot=bot, category_id=int(category_id), actor=request.user, **serializer.validated_data
        )
        return Response(ProductCategorySerializer(updated).data)

    @extend_schema(request=ProductWriteSerializer, responses={200: ProductSerializer(many=True)})
    @action(detail=True, methods=["get", "post"], url_path="products")
    def products(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            products = commerce_services.list_products(bot.pk)
            return Response(ProductSerializer(products, many=True, context=self.get_serializer_context()).data)

        serializer = ProductWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = commerce_services.create_product(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(
            ProductSerializer(created, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=ProductWriteSerializer, responses=ProductSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"products/(?P<product_id>\d+)")
    def product_detail(self, request: Request, public_id: str, product_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            commerce_services.delete_product(bot=bot, product_id=int(product_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = ProductWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = commerce_services.update_product(
            bot=bot, product_id=int(product_id), actor=request.user, **serializer.validated_data
        )
        return Response(ProductSerializer(updated, context=self.get_serializer_context()).data)

    @extend_schema(request=ImageUploadSerializer, responses={201: ProductImageSerializer})
    @action(detail=True, methods=["post"], url_path=r"products/(?P<product_id>\d+)/images")
    def product_images(self, request: Request, public_id: str, product_id: str) -> Response:
        bot = self.get_object()
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = commerce_services.add_product_image(
            bot=bot, product_id=int(product_id), actor=request.user,
            upload=serializer.validated_data["file"],
        )
        return Response(ProductImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"product-images/(?P<image_id>\d+)")
    def product_image_detail(self, request: Request, public_id: str, image_id: str) -> Response:
        bot = self.get_object()
        commerce_services.delete_product_image(bot=bot, image_id=int(image_id), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -- commerce: property listings ------------------------------------------------
    @extend_schema(request=PropertyListingWriteSerializer, responses={200: PropertyListingSerializer(many=True)})
    @action(detail=True, methods=["get", "post"], url_path="properties")
    def properties(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            listings = commerce_services.list_properties(bot.pk)
            return Response(PropertyListingSerializer(listings, many=True, context=self.get_serializer_context()).data)

        serializer = PropertyListingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = commerce_services.create_property(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(
            PropertyListingSerializer(created, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=PropertyListingWriteSerializer, responses=PropertyListingSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"properties/(?P<property_id>\d+)")
    def property_detail(self, request: Request, public_id: str, property_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            commerce_services.delete_property(bot=bot, property_id=int(property_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = PropertyListingWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = commerce_services.update_property(
            bot=bot, property_id=int(property_id), actor=request.user, **serializer.validated_data
        )
        return Response(PropertyListingSerializer(updated, context=self.get_serializer_context()).data)

    @extend_schema(request=ImageUploadSerializer, responses={201: PropertyImageSerializer})
    @action(detail=True, methods=["post"], url_path=r"properties/(?P<property_id>\d+)/images")
    def property_images(self, request: Request, public_id: str, property_id: str) -> Response:
        bot = self.get_object()
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = commerce_services.add_property_image(
            bot=bot, property_id=int(property_id), actor=request.user,
            upload=serializer.validated_data["file"],
        )
        return Response(PropertyImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"property-images/(?P<image_id>\d+)")
    def property_image_detail(self, request: Request, public_id: str, image_id: str) -> Response:
        bot = self.get_object()
        commerce_services.delete_property_image(bot=bot, image_id=int(image_id), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -- commerce: courses -----------------------------------------------------------
    @extend_schema(request=CourseOfferingWriteSerializer, responses={200: CourseOfferingSerializer(many=True)})
    @action(detail=True, methods=["get", "post"], url_path="courses")
    def courses(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            courses = commerce_services.list_courses(bot.pk)
            return Response(CourseOfferingSerializer(courses, many=True, context=self.get_serializer_context()).data)

        serializer = CourseOfferingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = commerce_services.create_course(bot=bot, actor=request.user, **serializer.validated_data)
        return Response(
            CourseOfferingSerializer(created, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=CourseOfferingWriteSerializer, responses=CourseOfferingSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"courses/(?P<course_id>\d+)")
    def course_detail(self, request: Request, public_id: str, course_id: str) -> Response:
        bot = self.get_object()

        if request.method == "DELETE":
            commerce_services.delete_course(bot=bot, course_id=int(course_id), actor=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = CourseOfferingWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = commerce_services.update_course(
            bot=bot, course_id=int(course_id), actor=request.user, **serializer.validated_data
        )
        return Response(CourseOfferingSerializer(updated, context=self.get_serializer_context()).data)

    @extend_schema(request=ImageUploadSerializer, responses=CourseOfferingSerializer)
    @action(detail=True, methods=["post"], url_path=r"courses/(?P<course_id>\d+)/thumbnail")
    def course_thumbnail(self, request: Request, public_id: str, course_id: str) -> Response:
        bot = self.get_object()
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = commerce_services.set_course_thumbnail(
            bot=bot, course_id=int(course_id), actor=request.user,
            upload=serializer.validated_data["file"],
        )
        return Response(CourseOfferingSerializer(course, context=self.get_serializer_context()).data)

    # -- commerce: orders & table reservations -------------------------------------
    @extend_schema(responses=BusinessOrderSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="business-orders")
    def business_orders(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        return Response(
            BusinessOrderSerializer(
                commerce_services.list_orders(bot), many=True, context=self.get_serializer_context()
            ).data
        )

    @extend_schema(responses=BusinessOrderSerializer)
    @action(detail=True, methods=["post"], url_path=r"business-orders/(?P<order_id>[^/.]+)/cancel")
    def cancel_business_order(self, request: Request, public_id: str, order_id: str) -> Response:
        bot = self.get_object()
        order = commerce_services.cancel_order(bot=bot, order_id=order_id, actor=request.user)
        return Response(BusinessOrderSerializer(order, context=self.get_serializer_context()).data)

    @extend_schema(responses=TableReservationSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="table-reservations")
    def table_reservations(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        return Response(TableReservationSerializer(commerce_services.list_reservations(bot), many=True).data)

    @extend_schema(responses=TableReservationSerializer)
    @action(detail=True, methods=["post"], url_path=r"table-reservations/(?P<reservation_id>[^/.]+)/cancel")
    def cancel_table_reservation(self, request: Request, public_id: str, reservation_id: str) -> Response:
        bot = self.get_object()
        reservation = commerce_services.cancel_reservation(
            bot=bot, reservation_id=reservation_id, actor=request.user
        )
        return Response(TableReservationSerializer(reservation).data)

    # -- ai: configuration ----------------------------------------------------------
    @extend_schema(request=AiConfigurationUpdateSerializer, responses=AiConfigurationSerializer)
    @action(detail=True, methods=["get", "patch"], url_path="ai-configuration")
    def ai_configuration(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            config = ai_services.get_or_create_configuration(bot)
            return Response(AiConfigurationSerializer(config).data)

        serializer = AiConfigurationUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        config = ai_services.update_configuration(
            bot=bot, actor=request.user, **serializer.validated_data
        )
        return Response(AiConfigurationSerializer(config).data)

    @extend_schema(responses=AiUsageSummarySerializer)
    @action(detail=True, methods=["get"], url_path="ai-usage")
    def ai_usage(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()
        used = ai_services.usage_this_period(bot)
        budget = ai_services.effective_budget(bot)
        return Response(
            {
                "summary": AiUsageSummarySerializer(
                    {"used_tokens": used, "budget": budget, "remaining": max(budget - used, 0)}
                ).data,
                "records": AiUsageRecordSerializer(ai_services.list_usage(bot), many=True).data,
            }
        )

    # -- ai: knowledge base documents -------------------------------------------------
    @extend_schema(
        request=KnowledgeDocumentCreateSerializer, responses={200: KnowledgeDocumentSerializer(many=True)}
    )
    @action(detail=True, methods=["get", "post"], url_path="ai-documents")
    def ai_documents(self, request: Request, public_id: str) -> Response:
        bot = self.get_object()

        if request.method == "GET":
            return Response(
                KnowledgeDocumentSerializer(ai_services.list_documents(bot), many=True).data
            )

        serializer = KnowledgeDocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = ai_services.ingest_document(
            bot=bot, actor=request.user, **serializer.validated_data
        )
        return Response(KnowledgeDocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"ai-documents/(?P<document_id>[^/.]+)")
    def ai_document_detail(self, request: Request, public_id: str, document_id: str) -> Response:
        bot = self.get_object()
        ai_services.delete_document(bot=bot, document_id=document_id, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
