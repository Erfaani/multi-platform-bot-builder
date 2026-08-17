from __future__ import annotations

from rest_framework import serializers

from apps.core.formatting import money_to_representation
from apps.orders.domain.state_machine import Actor, OrderStatus, allowed_targets
from apps.orders.models import Order, OrderEvent, OrderItem


class PlaceOrderSerializer(serializers.Serializer):
    quote = serializers.UUIDField()


class OrderItemSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    unit_amount = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "price_key",
            "label",
            "feature_slug",
            "quantity",
            "billing_kind",
            "unit_amount",
            "amount",
        )

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_amount(self, obj: OrderItem) -> dict | None:
        return money_to_representation(obj.amount, locale=self._locale())

    def get_unit_amount(self, obj: OrderItem) -> dict | None:
        return money_to_representation(obj.unit_amount, locale=self._locale())


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ("from_status", "to_status", "actor_type", "reason", "created_at")


class OrderSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    template = serializers.CharField(source="template.slug", read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    subtotal_once = serializers.SerializerMethodField()
    subtotal_recurring = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    target_bot = serializers.UUIDField(source="target_bot.public_id", read_only=True, default=None)

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "status",
            "kind",
            "template",
            "target_bot",
            "platforms",
            "features",
            "business_snapshot",
            "currency",
            "locale",
            "items",
            "events",
            "subtotal_once",
            "subtotal_recurring",
            "discount",
            "discount_reason",
            "total",
            "available_actions",
            "payment",
            "placed_at",
            "paid_at",
            "activated_at",
            "created_at",
        )

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_subtotal_once(self, obj: Order) -> dict | None:
        return money_to_representation(obj.subtotal_once, locale=self._locale())

    def get_subtotal_recurring(self, obj: Order) -> dict | None:
        return money_to_representation(obj.subtotal_recurring, locale=self._locale())

    def get_discount(self, obj: Order) -> dict | None:
        from apps.core.money import Money

        return money_to_representation(
            Money(obj.discount_minor, obj.currency), locale=self._locale()
        )

    def get_total(self, obj: Order) -> dict | None:
        return money_to_representation(obj.total, locale=self._locale())

    def get_available_actions(self, obj: Order) -> list[str]:
        """What *this customer* may do next — derived from the state machine.

        The UI never hard-codes button visibility; it asks.
        """
        return [status.value for status in allowed_targets(obj.status, Actor.CUSTOMER)]

    def get_payment(self, obj: Order) -> dict | None:
        payment = obj.payments.order_by("-created_at").first()
        if payment is None:
            return None
        return {
            "id": str(payment.public_id),
            "status": payment.status,
            "method": payment.payment_method.name,
            "rejection_reason": payment.rejection_reason,
            "submitted_at": payment.submitted_at,
        }


class OrderSummarySerializer(serializers.ModelSerializer):
    """Lighter shape for the orders list."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("id", "number", "status", "currency", "total", "created_at")

    def get_total(self, obj: Order) -> dict | None:
        return money_to_representation(obj.total, locale=self.context.get("locale", "en"))


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
