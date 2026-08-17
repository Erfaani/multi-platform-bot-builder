from __future__ import annotations

from rest_framework import serializers

from apps.core.formatting import money_to_representation
from apps.payments.models import Payment, PaymentMethod
from apps.payments.providers import provider_for


class PaymentMethodSerializer(serializers.ModelSerializer):
    """Public view of a payment method.

    `config` is exposed only through the provider's `instructions()` — the model field
    itself is never serialized, so adding an internal key to it later cannot leak.
    """

    id = serializers.UUIDField(source="public_id", read_only=True)
    minimum_amount = serializers.SerializerMethodField()
    requires_transaction_hash = serializers.SerializerMethodField()

    class Meta:
        model = PaymentMethod
        fields = (
            "id",
            "kind",
            "name",
            "currency",
            "network",
            "minimum_amount",
            "requires_transaction_hash",
            "sort_order",
        )

    def get_minimum_amount(self, obj: PaymentMethod) -> dict | None:
        return money_to_representation(
            obj.minimum_amount, locale=self.context.get("locale", "en")
        )

    def get_requires_transaction_hash(self, obj: PaymentMethod) -> bool:
        return provider_for(obj).proof_requirements(method=obj).requires_tx_hash


class StartPaymentSerializer(serializers.Serializer):
    payment_method = serializers.UUIDField()


class SubmitProofSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    tx_hash = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    sender_wallet = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    payer_note = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class InstructionFieldSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()
    copyable = serializers.BooleanField(required=False, default=False)


class PaymentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    order = serializers.UUIDField(source="order.public_id", read_only=True)
    order_number = serializers.IntegerField(source="order.number", read_only=True)
    method = PaymentMethodSerializer(source="payment_method", read_only=True)
    amount = serializers.SerializerMethodField()
    instructions = serializers.SerializerMethodField()
    proof = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = (
            "id",
            "order",
            "order_number",
            "status",
            "method",
            "amount",
            "tx_hash",
            "instructions",
            "proof",
            "rejection_reason",
            "submitted_at",
            "reviewed_at",
            "created_at",
        )
        # `internal_note` is deliberately absent: it is staff-only (spec §14).

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_amount(self, obj: Payment) -> dict | None:
        return money_to_representation(obj.amount, locale=self._locale())

    def get_instructions(self, obj: Payment) -> dict:
        from apps.payments.services import instructions_for

        instructions = instructions_for(obj)
        return {
            "headline": instructions.headline,
            "fields": instructions.fields,
            "notes": instructions.notes,
            "copyable": instructions.copyable,
        }

    def get_proof(self, obj: Payment) -> dict:
        requirements = provider_for(obj.payment_method).proof_requirements(
            method=obj.payment_method
        )
        return {
            "requires_file": requirements.requires_file,
            "requires_tx_hash": requirements.requires_tx_hash,
            "optional_fields": list(requirements.optional_fields),
            "receipts": obj.receipts.count(),
        }
