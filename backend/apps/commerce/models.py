"""Commerce: product catalogue, cart, orders, table reservations (DATABASE.md §9).

`food_ordering` (the manifest slug) has no separate models or handlers here — its
manifest already declares it as `product_catalog` + `cart_orders` with a media-groups
platform requirement, not a different flow. A restaurant's menu is a product catalogue;
"ordering food" is checking out a cart. Building a parallel path would duplicate this
one for no behavioural difference.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CurrencyCodeField, PublicIdModel, TenantOwnedModel
from apps.core.money import MoneyProxy


class ProductCategory(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="product_categories")
    name = models.CharField(max_length=128)
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "product_category"
        ordering = ("sort_order", "id")
        verbose_name_plural = "product categories"

    def __str__(self) -> str:
        return self.name


class Product(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(
        ProductCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )

    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    price_minor = models.BigIntegerField()
    currency = CurrencyCodeField()
    price = MoneyProxy("price_minor", "currency")

    #: Null means not tracked — always orderable. Zero means genuinely out of stock.
    stock = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "product"
        ordering = ("sort_order", "id")
        indexes = [models.Index(fields=["bot", "is_active"], name="product_bot_active_idx")]

    def __str__(self) -> str:
        return self.name

    @property
    def in_stock(self) -> bool:
        return self.stock is None or self.stock > 0


class Cart(TenantOwnedModel):
    """One open cart per contact per bot — reused across the conversation until checkout."""

    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="carts")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact", on_delete=models.CASCADE, related_name="carts"
    )

    class Meta:
        db_table = "cart"
        constraints = [models.UniqueConstraint(fields=["bot", "contact"], name="cart_bot_contact_uniq")]

    def __str__(self) -> str:
        return f"cart for contact #{self.contact_id}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "cart_item"
        constraints = [models.UniqueConstraint(fields=["cart", "product"], name="cart_item_cart_product_uniq")]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product_id}"


class BusinessOrderStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    CONFIRMED = "CONFIRMED", _("Confirmed")
    CANCELLED = "CANCELLED", _("Cancelled")
    COMPLETED = "COMPLETED", _("Completed")


class BusinessOrder(PublicIdModel, TenantOwnedModel):
    """An order placed *with the customer's business* through their bot.

    Unrelated to `apps.orders.Order`, which is this platform's own SaaS billing —
    conflating the two would mix what the clinic charges its patients with what the
    clinic pays us.
    """

    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="business_orders")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact", on_delete=models.CASCADE, related_name="business_orders"
    )
    status = models.CharField(
        max_length=16, choices=BusinessOrderStatus.choices, default=BusinessOrderStatus.PENDING
    )

    subtotal_minor = models.BigIntegerField()
    currency = CurrencyCodeField()
    subtotal = MoneyProxy("subtotal_minor", "currency")

    delivery_address = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "business_order"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["bot", "-created_at"], name="business_order_bot_time_idx")]

    def __str__(self) -> str:
        return f"Order #{self.pk} ({self.status})"


class BusinessOrderItem(models.Model):
    """Price and name are snapshotted — a later catalogue edit must not rewrite history."""

    order = models.ForeignKey(BusinessOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")

    product_name = models.CharField(max_length=128)
    unit_price_minor = models.BigIntegerField()
    currency = CurrencyCodeField()
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "business_order_item"

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product_name}"

    @property
    def amount_minor(self) -> int:
        return self.unit_price_minor * self.quantity


class TableReservationStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", _("Confirmed")
    CANCELLED = "CANCELLED", _("Cancelled")
    COMPLETED = "COMPLETED", _("Completed")


class TableReservation(PublicIdModel, TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="table_reservations")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact", on_delete=models.CASCADE, related_name="table_reservations"
    )
    party_size = models.PositiveSmallIntegerField()
    starts_at = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=TableReservationStatus.choices, default=TableReservationStatus.CONFIRMED
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "table_reservation"
        ordering = ("starts_at",)
        indexes = [models.Index(fields=["bot", "starts_at"], name="table_reservation_bot_time_idx")]

    def __str__(self) -> str:
        return f"table for {self.party_size} at {self.starts_at}"
