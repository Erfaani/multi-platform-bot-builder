"""Commerce use cases: catalogue browsing, cart, checkout, table reservations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.audit.services import record_audit
from apps.core.errors import ConflictError, NotFoundError, ValidationError
from apps.core.events import publish

from apps.commerce.models import (
    BusinessOrder,
    BusinessOrderItem,
    BusinessOrderStatus,
    Cart,
    CartItem,
    CourseOffering,
    Product,
    ProductCategory,
    ProductImage,
    PropertyImage,
    PropertyListing,
    TableReservation,
)

# --------------------------------------------------------------------------- catalogue


def list_categories(bot_id: int) -> list[ProductCategory]:
    return list(ProductCategory.objects.filter(bot_id=bot_id, is_active=True).order_by("sort_order", "id"))


def list_products(bot_id: int, *, category_id: int | None = None) -> list[Product]:
    qs = Product.objects.filter(bot_id=bot_id, is_active=True).select_related("category")
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    return list(qs.order_by("sort_order", "id"))


@transaction.atomic
def create_category(*, bot, actor, name: str, sort_order: int = 100) -> ProductCategory:
    name = name.strip()
    if not name:
        raise ValidationError(code="commerce.category_name_required", field_errors={"name": ["Required."]})
    category = ProductCategory.objects.create(tenant=bot.tenant, bot=bot, name=name[:128], sort_order=sort_order)
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.category_created", resource_type="product_category",
        resource_id=str(category.pk), tenant=bot.tenant,
    )
    return category


@transaction.atomic
def update_category(*, bot, category_id: int, actor, **fields) -> ProductCategory:
    category = ProductCategory.objects.filter(bot=bot, pk=category_id).first()
    if category is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in ("name", "sort_order", "is_active"):
        if key in fields and fields[key] is not None:
            setattr(category, key, fields[key])
            changed.append(key)

    if changed:
        category.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor, action="commerce.category_updated", resource_type="product_category",
            resource_id=str(category.pk), tenant=bot.tenant, metadata={"fields": changed},
        )
    return category


@transaction.atomic
def delete_category(*, bot, category_id: int, actor) -> None:
    category = ProductCategory.objects.filter(bot=bot, pk=category_id).first()
    if category is None:
        raise NotFoundError()
    category.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.category_deleted", resource_type="product_category",
        resource_id=str(category_id), tenant=bot.tenant,
    )


@transaction.atomic
def create_product(*, bot, actor, name: str, price_minor: int, category_id: int | None = None, **fields) -> Product:
    name = name.strip()
    if not name:
        raise ValidationError(code="commerce.product_name_required", field_errors={"name": ["Required."]})
    if price_minor < 0:
        raise ValidationError(code="commerce.invalid_price", field_errors={"price_minor": ["Must not be negative."]})

    product = Product.objects.create(
        tenant=bot.tenant,
        bot=bot,
        category_id=category_id,
        name=name[:128],
        description=fields.get("description", ""),
        price_minor=price_minor,
        currency=fields.get("currency") or bot.currency,
        stock=fields.get("stock"),
        sort_order=fields.get("sort_order", 100),
    )
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.product_created", resource_type="product",
        resource_id=str(product.pk), tenant=bot.tenant,
    )
    return product


@transaction.atomic
def update_product(*, bot, product_id: int, actor, **fields) -> Product:
    product = Product.objects.filter(bot=bot, pk=product_id).first()
    if product is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in ("name", "description", "price_minor", "currency", "category_id", "stock", "is_active", "sort_order"):
        if key in fields and fields[key] is not None:
            setattr(product, key, fields[key])
            changed.append(key)

    if changed:
        product.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor, action="commerce.product_updated", resource_type="product",
            resource_id=str(product.pk), tenant=bot.tenant, metadata={"fields": changed},
        )
    return product


@transaction.atomic
def delete_product(*, bot, product_id: int, actor) -> None:
    product = Product.objects.filter(bot=bot, pk=product_id).first()
    if product is None:
        raise NotFoundError()
    product.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.product_deleted", resource_type="product",
        resource_id=str(product_id), tenant=bot.tenant,
    )


@transaction.atomic
def add_product_image(*, bot, product_id: int, actor, upload) -> ProductImage:
    from apps.core.files import PUBLIC_IMAGE_POLICY, validate_and_sanitise

    product = Product.objects.filter(bot=bot, pk=product_id).first()
    if product is None:
        raise NotFoundError()

    safe = validate_and_sanitise(upload, PUBLIC_IMAGE_POLICY)
    image = ProductImage(product=product)
    image.file.save(safe.filename, safe.content, save=False)
    image.save()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.product_image_added", resource_type="product_image",
        resource_id=str(image.pk), tenant=bot.tenant, metadata={"product": product.pk},
    )
    return image


@transaction.atomic
def delete_product_image(*, bot, image_id: int, actor) -> None:
    image = ProductImage.objects.filter(product__bot=bot, pk=image_id).first()
    if image is None:
        raise NotFoundError()
    image.file.delete(save=False)
    image.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.product_image_deleted", resource_type="product_image",
        resource_id=str(image_id), tenant=bot.tenant,
    )


# --------------------------------------------------------------------------- property listings


def list_properties(bot_id: int) -> list[PropertyListing]:
    return list(
        PropertyListing.objects.filter(bot_id=bot_id, is_active=True)
        .prefetch_related("images")
        .order_by("sort_order", "id")
    )


@transaction.atomic
def create_property(*, bot, actor, title: str, listing_type: str, property_type: str, price_minor: int, **fields) -> PropertyListing:
    title = title.strip()
    if not title:
        raise ValidationError(code="commerce.property_title_required", field_errors={"title": ["Required."]})
    if price_minor < 0:
        raise ValidationError(code="commerce.invalid_price", field_errors={"price_minor": ["Must not be negative."]})

    listing = PropertyListing.objects.create(
        tenant=bot.tenant,
        bot=bot,
        title=title[:128],
        description=fields.get("description", ""),
        listing_type=listing_type,
        property_type=property_type,
        bedrooms=fields.get("bedrooms"),
        bathrooms=fields.get("bathrooms"),
        area_sqm=fields.get("area_sqm"),
        address=fields.get("address", "")[:255],
        price_minor=price_minor,
        currency=fields.get("currency") or bot.currency,
        sort_order=fields.get("sort_order", 100),
    )
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.property_created", resource_type="property_listing",
        resource_id=str(listing.pk), tenant=bot.tenant,
    )
    return listing


@transaction.atomic
def update_property(*, bot, property_id: int, actor, **fields) -> PropertyListing:
    listing = PropertyListing.objects.filter(bot=bot, pk=property_id).first()
    if listing is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in (
        "title", "description", "listing_type", "property_type", "bedrooms", "bathrooms",
        "area_sqm", "address", "price_minor", "currency", "is_active", "sort_order",
    ):
        if key in fields and fields[key] is not None:
            setattr(listing, key, fields[key])
            changed.append(key)

    if changed:
        listing.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor, action="commerce.property_updated", resource_type="property_listing",
            resource_id=str(listing.pk), tenant=bot.tenant, metadata={"fields": changed},
        )
    return listing


@transaction.atomic
def delete_property(*, bot, property_id: int, actor) -> None:
    listing = PropertyListing.objects.filter(bot=bot, pk=property_id).first()
    if listing is None:
        raise NotFoundError()
    listing.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.property_deleted", resource_type="property_listing",
        resource_id=str(property_id), tenant=bot.tenant,
    )


@transaction.atomic
def add_property_image(*, bot, property_id: int, actor, upload) -> PropertyImage:
    from apps.core.files import PUBLIC_IMAGE_POLICY, validate_and_sanitise

    listing = PropertyListing.objects.filter(bot=bot, pk=property_id).first()
    if listing is None:
        raise NotFoundError()

    safe = validate_and_sanitise(upload, PUBLIC_IMAGE_POLICY)
    image = PropertyImage(property=listing)
    image.file.save(safe.filename, safe.content, save=False)
    image.save()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.property_image_added", resource_type="property_image",
        resource_id=str(image.pk), tenant=bot.tenant, metadata={"property": listing.pk},
    )
    return image


@transaction.atomic
def delete_property_image(*, bot, image_id: int, actor) -> None:
    image = PropertyImage.objects.filter(property__bot=bot, pk=image_id).first()
    if image is None:
        raise NotFoundError()
    image.file.delete(save=False)
    image.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.property_image_deleted", resource_type="property_image",
        resource_id=str(image_id), tenant=bot.tenant,
    )


# --------------------------------------------------------------------------- courses


def list_courses(bot_id: int) -> list[CourseOffering]:
    return list(CourseOffering.objects.filter(bot_id=bot_id, is_active=True).order_by("sort_order", "id"))


@transaction.atomic
def create_course(*, bot, actor, title: str, price_minor: int, **fields) -> CourseOffering:
    title = title.strip()
    if not title:
        raise ValidationError(code="commerce.course_title_required", field_errors={"title": ["Required."]})
    if price_minor < 0:
        raise ValidationError(code="commerce.invalid_price", field_errors={"price_minor": ["Must not be negative."]})

    course = CourseOffering.objects.create(
        tenant=bot.tenant,
        bot=bot,
        title=title[:128],
        description=fields.get("description", ""),
        instructor_name=fields.get("instructor_name", "")[:128],
        price_minor=price_minor,
        currency=fields.get("currency") or bot.currency,
        starts_at=fields.get("starts_at"),
        duration_label=fields.get("duration_label", "")[:64],
        capacity=fields.get("capacity"),
        sort_order=fields.get("sort_order", 100),
    )
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.course_created", resource_type="course_offering",
        resource_id=str(course.pk), tenant=bot.tenant,
    )
    return course


@transaction.atomic
def update_course(*, bot, course_id: int, actor, **fields) -> CourseOffering:
    course = CourseOffering.objects.filter(bot=bot, pk=course_id).first()
    if course is None:
        raise NotFoundError()

    changed: list[str] = []
    for key in (
        "title", "description", "instructor_name", "price_minor", "currency", "starts_at",
        "duration_label", "capacity", "enrolled_count", "is_active", "sort_order",
    ):
        if key in fields and fields[key] is not None:
            setattr(course, key, fields[key])
            changed.append(key)

    if changed:
        course.save(update_fields=[*changed, "updated_at"])
        bot.configuration.bump()
        record_audit(
            actor=actor, action="commerce.course_updated", resource_type="course_offering",
            resource_id=str(course.pk), tenant=bot.tenant, metadata={"fields": changed},
        )
    return course


@transaction.atomic
def delete_course(*, bot, course_id: int, actor) -> None:
    course = CourseOffering.objects.filter(bot=bot, pk=course_id).first()
    if course is None:
        raise NotFoundError()
    course.delete()
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.course_deleted", resource_type="course_offering",
        resource_id=str(course_id), tenant=bot.tenant,
    )


@transaction.atomic
def set_course_thumbnail(*, bot, course_id: int, actor, upload) -> CourseOffering:
    from apps.core.files import PUBLIC_IMAGE_POLICY, validate_and_sanitise

    course = CourseOffering.objects.filter(bot=bot, pk=course_id).first()
    if course is None:
        raise NotFoundError()

    safe = validate_and_sanitise(upload, PUBLIC_IMAGE_POLICY)
    if course.thumbnail:
        course.thumbnail.delete(save=False)
    course.thumbnail.save(safe.filename, safe.content, save=False)
    course.save(update_fields=["thumbnail", "updated_at"])
    bot.configuration.bump()
    record_audit(
        actor=actor, action="commerce.course_thumbnail_set", resource_type="course_offering",
        resource_id=str(course.pk), tenant=bot.tenant,
    )
    return course


# --------------------------------------------------------------------------- cart


def get_or_create_cart(bot, contact) -> Cart:
    cart, _ = Cart.objects.get_or_create(tenant=bot.tenant, bot=bot, contact=contact)
    return cart


@transaction.atomic
def add_to_cart(*, cart: Cart, product: Product, quantity: int = 1) -> CartItem:
    if not product.in_stock:
        raise ConflictError(code="commerce.out_of_stock", message="That item is out of stock.")

    item, created = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": quantity})
    if not created:
        item.quantity += quantity
        item.save(update_fields=["quantity"])
    return item


def cart_items(cart: Cart) -> list[CartItem]:
    return list(cart.items.select_related("product").all())


def cart_total_minor(cart: Cart) -> int:
    return sum(item.product.price_minor * item.quantity for item in cart_items(cart))


@transaction.atomic
def clear_cart(cart: Cart) -> None:
    cart.items.all().delete()


@transaction.atomic
def checkout(*, cart: Cart, delivery_address: str = "", notes: str = "") -> BusinessOrder:
    items = cart_items(cart)
    if not items:
        raise ValidationError(code="commerce.empty_cart", message="Your cart is empty.")

    currency = items[0].product.currency
    order = BusinessOrder.objects.create(
        tenant=cart.tenant,
        bot=cart.bot,
        contact=cart.contact,
        status=BusinessOrderStatus.CONFIRMED,
        subtotal_minor=sum(item.product.price_minor * item.quantity for item in items),
        currency=currency,
        delivery_address=delivery_address[:255],
        notes=notes[:500],
    )
    BusinessOrderItem.objects.bulk_create(
        [
            BusinessOrderItem(
                order=order,
                product=item.product,
                product_name=item.product.name,
                unit_price_minor=item.product.price_minor,
                currency=item.product.currency,
                quantity=item.quantity,
            )
            for item in items
        ]
    )
    clear_cart(cart)

    record_audit(
        actor=None, action="commerce.order_placed", resource_type="business_order",
        resource_id=str(order.public_id), tenant=cart.tenant, metadata={"total_minor": order.subtotal_minor},
    )
    publish(
        "commerce.order_placed",
        {
            "tenant_id": str(cart.tenant.public_id),
            "bot_id": str(cart.bot.public_id),
            "dedupe_key": f"business_order:{order.public_id}",
            "total": f"{order.subtotal_minor / (10 ** 2):.2f} {currency}",
        },
    )
    return order


def list_orders(bot) -> list[BusinessOrder]:
    return list(BusinessOrder.objects.filter(bot=bot).select_related("contact").prefetch_related("items"))


@transaction.atomic
def cancel_order(*, bot, order_id, actor) -> BusinessOrder:
    order = BusinessOrder.objects.filter(bot=bot, public_id=order_id).first()
    if order is None:
        raise NotFoundError()
    if order.status not in {BusinessOrderStatus.PENDING, BusinessOrderStatus.CONFIRMED}:
        raise ConflictError(code="commerce.order_not_cancellable", message="This order cannot be cancelled.")

    order.status = BusinessOrderStatus.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    record_audit(
        actor=actor, action="commerce.order_cancelled", resource_type="business_order",
        resource_id=str(order.public_id), tenant=bot.tenant,
    )
    return order


# --------------------------------------------------------------------------- table reservation

#: A table reservation has no per-table inventory to check against — unlike
#: appointments, this deliberately does not guard against over-booking a capacity
#: nobody has told us about yet (see PHASES.md). It offers real open hours, on a real
#: step size, and nothing more.
RESERVATION_STEP_MINUTES = 30
RESERVATION_WINDOW_DAYS = 14


def available_times(*, bot_id: int, timezone: str, day: date) -> list[datetime]:
    from apps.businesses.models import WorkingHours

    tz = ZoneInfo(timezone or "UTC")
    today_local = dj_timezone.now().astimezone(tz).date()
    if day < today_local or day > today_local + timedelta(days=RESERVATION_WINDOW_DAYS):
        return []

    earliest = dj_timezone.now() + timedelta(minutes=RESERVATION_STEP_MINUTES)
    step = timedelta(minutes=RESERVATION_STEP_MINUTES)

    rows = WorkingHours.objects.filter(bot_id=bot_id, weekday=day.weekday(), is_closed=False).exclude(
        opens_at__isnull=True
    ).exclude(closes_at__isnull=True)

    times: list[datetime] = []
    for row in rows:
        opens = datetime.combine(day, row.opens_at, tzinfo=tz).astimezone(ZoneInfo("UTC"))
        closes = datetime.combine(day, row.closes_at, tzinfo=tz).astimezone(ZoneInfo("UTC"))
        cursor = opens
        while cursor < closes:
            if cursor >= earliest:
                times.append(cursor)
            cursor += step
    return times


@transaction.atomic
def reserve_table(*, bot, contact, party_size: int, starts_at: datetime, notes: str = "") -> TableReservation:
    if party_size < 1:
        raise ValidationError(code="commerce.invalid_party_size", field_errors={"party_size": ["At least 1."]})
    if starts_at < dj_timezone.now():
        raise ConflictError(code="commerce.slot_in_the_past", message="That time has already passed.")

    reservation = TableReservation.objects.create(
        tenant=bot.tenant, bot=bot, contact=contact, party_size=party_size, starts_at=starts_at, notes=notes[:255]
    )
    record_audit(
        actor=None, action="commerce.table_reserved", resource_type="table_reservation",
        resource_id=str(reservation.public_id), tenant=bot.tenant,
    )
    return reservation


def list_reservations(bot) -> list[TableReservation]:
    return list(TableReservation.objects.filter(bot=bot).select_related("contact"))


@transaction.atomic
def cancel_reservation(*, bot, reservation_id, actor) -> TableReservation:
    from apps.commerce.models import TableReservationStatus

    reservation = TableReservation.objects.filter(bot=bot, public_id=reservation_id).first()
    if reservation is None:
        raise NotFoundError()
    if reservation.status != TableReservationStatus.CONFIRMED:
        raise ConflictError(code="commerce.reservation_not_cancellable", message="This reservation cannot be cancelled.")

    reservation.status = TableReservationStatus.CANCELLED
    reservation.save(update_fields=["status", "updated_at"])
    return reservation
