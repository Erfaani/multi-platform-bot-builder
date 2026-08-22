from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import NotFoundError
from apps.customers.api.serializers import (
    AcceptInvitationSerializer,
    AddMemberResultSerializer,
    AddMemberSerializer,
    ChannelIdentitySerializer,
    ChannelLinkCodeSerializer,
    ChannelLinkRequestSerializer,
    InvitationPreviewSerializer,
    TenantCreateSerializer,
    TenantInvitationSerializer,
    TenantMembershipSerializer,
    TenantSerializer,
)
from apps.customers.models import Tenant, TenantInvitation, TenantMembership
from apps.customers.resolution import resolve_active_tenant
from apps.customers.services import (
    accept_invitation,
    create_link_code,
    create_tenant,
    get_invitation_preview,
    invite_or_add_member,
    list_channel_identities,
    list_pending_invitations,
    remove_member,
    revoke_invitation,
    unlink_channel_identity,
)


class TenantViewSet(viewsets.GenericViewSet):
    """Workspaces the caller belongs to.

    Not a ``TenantScopedViewSet``: this is the endpoint that *chooses* the tenant, so
    it scopes by membership rather than by an already-resolved tenant.
    """

    serializer_class = TenantSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return Tenant.objects.filter(memberships__user=self.request.user).distinct()

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["roles_by_tenant_id"] = dict(
            TenantMembership.objects.filter(user=self.request.user).values_list(
                "tenant_id", "role"
            )
        )
        return context

    def _get_tenant_or_404(self, public_id: str) -> Tenant:
        tenant = self.get_queryset().filter(public_id=public_id).first()
        if tenant is None:
            raise NotFoundError()
        return tenant

    @extend_schema(responses=TenantSerializer(many=True))
    def list(self, request: Request) -> Response:
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    @extend_schema(responses=TenantSerializer)
    def retrieve(self, request: Request, public_id: str) -> Response:
        return Response(self.get_serializer(self._get_tenant_or_404(public_id)).data)

    @extend_schema(request=TenantCreateSerializer, responses={201: TenantSerializer})
    def create(self, request: Request) -> Response:
        serializer = TenantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = create_tenant(
            owner=request.user,
            name=data["name"],
            country=data.get("country", ""),
            default_locale=data.get("default_locale"),
            default_currency=data.get("default_currency"),
            timezone_name=data.get("timezone"),
        )
        return Response(
            self.get_serializer(tenant).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=TenantSerializer)
    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request: Request) -> Response:
        """Resolve which workspace this request would act on (ADR-0005)."""
        active = resolve_active_tenant(request)
        return Response(
            {
                **self.get_serializer(active.tenant).data,
                "role": active.membership.role,
                "scopes": sorted(active.membership.scopes),
            }
        )

    @extend_schema(responses=TenantMembershipSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request: Request, public_id: str) -> Response:
        tenant = self._get_tenant_or_404(public_id)
        memberships = TenantMembership.objects.select_related("user").filter(tenant=tenant)
        return Response(TenantMembershipSerializer(memberships, many=True).data)

    @extend_schema(request=AddMemberSerializer, responses={201: AddMemberResultSerializer})
    @members.mapping.post
    def add_member(self, request: Request, public_id: str) -> Response:
        """Add someone by account, or invite them by email if they have none yet."""
        tenant = self._get_tenant_or_404(public_id)

        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        outcome, result = invite_or_add_member(
            tenant=tenant,
            actor=request.user,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
        )
        if outcome == "added":
            payload = {"outcome": outcome, "membership": TenantMembershipSerializer(result).data}
        else:
            payload = {"outcome": outcome, "invitation_email": result.email}
        return Response(payload, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"members/(?P<member_id>\d+)")
    def remove_member(self, request: Request, public_id: str, member_id: str) -> Response:
        tenant = self._get_tenant_or_404(public_id)
        membership = TenantMembership.objects.filter(tenant=tenant, pk=member_id).first()
        if membership is None:
            raise NotFoundError()
        remove_member(tenant=tenant, actor=request.user, membership=membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -- pending invitations -------------------------------------------------
    @extend_schema(responses=TenantInvitationSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="invitations")
    def invitations(self, request: Request, public_id: str) -> Response:
        tenant = self._get_tenant_or_404(public_id)
        pending = list_pending_invitations(tenant)
        return Response(TenantInvitationSerializer(pending, many=True).data)

    @extend_schema(responses={204: None})
    @action(
        detail=True, methods=["delete"], url_path=r"invitations/(?P<invitation_id>\d+)"
    )
    def revoke_invitation(self, request: Request, public_id: str, invitation_id: str) -> Response:
        tenant = self._get_tenant_or_404(public_id)
        invitation = TenantInvitation.objects.filter(tenant=tenant, pk=invitation_id).first()
        if invitation is None:
            raise NotFoundError()
        revoke_invitation(tenant=tenant, actor=request.user, invitation=invitation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationViewSet(viewsets.GenericViewSet):
    """Accepting an invite. Not tenant-scoped — the token itself is the authority."""

    permission_classes = (permissions.AllowAny,)

    @extend_schema(request=AcceptInvitationSerializer, responses=InvitationPreviewSerializer)
    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request: Request) -> Response:
        """Show which workspace this invites into, before the visitor logs in."""
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        invitation = get_invitation_preview(serializer.validated_data["token"])
        return Response(
            {
                "tenant_name": invitation.tenant.name,
                "role": invitation.role,
                "email": invitation.email,
            }
        )

    @extend_schema(
        request=AcceptInvitationSerializer, responses={200: TenantMembershipSerializer}
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="accept",
        permission_classes=[permissions.IsAuthenticated],
    )
    def accept(self, request: Request) -> Response:
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = accept_invitation(
            raw_token=serializer.validated_data["token"], user=request.user
        )
        return Response(TenantMembershipSerializer(membership).data)


class ChannelLinkViewSet(viewsets.GenericViewSet):
    """Linking a Telegram/Bale account to the caller's own website account (spec §47).

    Not tenant-scoped: a platform identity belongs to the *user*, not to any one
    workspace, so it works for the owner-admin menu on every bot they can already
    manage from the dashboard.
    """

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=ChannelIdentitySerializer(many=True))
    def list(self, request: Request) -> Response:
        return Response(
            ChannelIdentitySerializer(list_channel_identities(request.user), many=True).data
        )

    @extend_schema(request=ChannelLinkRequestSerializer, responses={201: ChannelLinkCodeSerializer})
    def create(self, request: Request) -> Response:
        serializer = ChannelLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        nonce = create_link_code(
            user=request.user,
            platform=serializer.validated_data["platform"],
            request_ip=request.META.get("REMOTE_ADDR"),
        )
        return Response(ChannelLinkCodeSerializer(nonce).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str) -> Response:
        unlink_channel_identity(user=request.user, identity_id=int(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)
