"""Commerce: product catalogue, cart, checkout, and table reservations
(Phase 7's commerce module)."""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from django.utils import timezone as dj_timezone

from apps.businesses.models import WorkingHours
from apps.commerce import services
from apps.commerce.models import BusinessOrder, BusinessOrderStatus, TableReservation
from apps.core.errors import ConflictError, ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def contact(provisioned_bot):
    from apps.bot_runtime.models import BusinessContact

    return BusinessContact.objects.create(
        tenant=provisioned_bot.tenant, bot=provisioned_bot, platform="telegram", platform_user_id="555"
    )


@pytest.fixture
def category(provisioned_bot):
    return services.create_category(bot=provisioned_bot, actor=None, name="Drinks")


@pytest.fixture
def product(provisioned_bot, category):
    return services.create_product(
        bot=provisioned_bot, actor=None, name="Latte", price_minor=450, category_id=category.pk
    )


class TestCatalogueServices:
    def test_create_requires_a_name(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_product(bot=provisioned_bot, actor=None, name=" ", price_minor=100)

    def test_negative_price_is_rejected(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_product(bot=provisioned_bot, actor=None, name="Latte", price_minor=-1)

    def test_update_and_delete_product(self, provisioned_bot, product):
        updated = services.update_product(bot=provisioned_bot, product_id=product.pk, actor=None, price_minor=500)
        assert updated.price_minor == 500

        services.delete_product(bot=provisioned_bot, product_id=product.pk, actor=None)
        assert not services.list_products(provisioned_bot.pk)

    def test_products_can_be_filtered_by_category(self, provisioned_bot, category, product):
        other_category = services.create_category(bot=provisioned_bot, actor=None, name="Food")
        services.create_product(bot=provisioned_bot, actor=None, name="Sandwich", price_minor=800, category_id=other_category.pk)

        assert [p.pk for p in services.list_products(provisioned_bot.pk, category_id=category.pk)] == [product.pk]

    def test_editing_a_product_bumps_the_runtime_cache(self, provisioned_bot, product):
        before = provisioned_bot.configuration.version
        services.update_product(bot=provisioned_bot, product_id=product.pk, actor=None, name="Cappuccino")
        provisioned_bot.configuration.refresh_from_db()
        assert provisioned_bot.configuration.version > before


class TestCart:
    def test_adding_the_same_product_twice_increases_quantity(self, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product)
        services.add_to_cart(cart=cart, product=product)

        items = services.cart_items(cart)
        assert len(items) == 1
        assert items[0].quantity == 2

    def test_out_of_stock_cannot_be_added(self, provisioned_bot, contact, category):
        product = services.create_product(
            bot=provisioned_bot, actor=None, name="Sold out", price_minor=100, category_id=category.pk, stock=0
        )
        cart = services.get_or_create_cart(provisioned_bot, contact)
        with pytest.raises(ConflictError):
            services.add_to_cart(cart=cart, product=product)

    def test_cart_total_sums_line_items(self, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product, quantity=3)
        assert services.cart_total_minor(cart) == 450 * 3

    def test_checkout_creates_an_order_and_clears_the_cart(self, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product, quantity=2)

        order = services.checkout(cart=cart)

        assert order.status == BusinessOrderStatus.CONFIRMED
        assert order.subtotal_minor == 450 * 2
        assert order.items.count() == 1
        assert services.cart_items(cart) == []

    def test_checkout_snapshots_the_price_even_if_it_later_changes(self, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product)
        order = services.checkout(cart=cart)

        services.update_product(bot=provisioned_bot, product_id=product.pk, actor=None, price_minor=999)

        assert order.items.get().unit_price_minor == 450

    def test_checking_out_an_empty_cart_is_rejected(self, provisioned_bot, contact):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        with pytest.raises(ValidationError):
            services.checkout(cart=cart)

    def test_cancel_order(self, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product)
        order = services.checkout(cart=cart)

        cancelled = services.cancel_order(bot=provisioned_bot, order_id=order.public_id, actor=None)
        assert cancelled.status == BusinessOrderStatus.CANCELLED

    def test_cancelling_twice_is_rejected(self, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product)
        order = services.checkout(cart=cart)
        services.cancel_order(bot=provisioned_bot, order_id=order.public_id, actor=None)

        with pytest.raises(ConflictError):
            services.cancel_order(bot=provisioned_bot, order_id=order.public_id, actor=None)


class TestTableReservation:
    def test_available_times_respect_working_hours(self, provisioned_bot):
        day = dj_timezone.now().date() + timedelta(days=1)
        WorkingHours.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, weekday=day.weekday(),
            opens_at=time(18, 0), closes_at=time(20, 0),
        )
        times = services.available_times(bot_id=provisioned_bot.pk, timezone="UTC", day=day)
        assert times
        assert all(time(18, 0) <= t.time() < time(20, 0) for t in times)

    def test_reserve_table(self, provisioned_bot, contact):
        starts_at = dj_timezone.now() + timedelta(days=1)
        reservation = services.reserve_table(bot=provisioned_bot, contact=contact, party_size=4, starts_at=starts_at)
        assert reservation.party_size == 4

    def test_cannot_reserve_in_the_past(self, provisioned_bot, contact):
        with pytest.raises(ConflictError):
            services.reserve_table(
                bot=provisioned_bot, contact=contact, party_size=2, starts_at=dj_timezone.now() - timedelta(hours=1)
            )

    def test_invalid_party_size_is_rejected(self, provisioned_bot, contact):
        with pytest.raises(ValidationError):
            services.reserve_table(
                bot=provisioned_bot, contact=contact, party_size=0, starts_at=dj_timezone.now() + timedelta(days=1)
            )

    def test_cancel_reservation(self, provisioned_bot, contact):
        reservation = services.reserve_table(
            bot=provisioned_bot, contact=contact, party_size=2, starts_at=dj_timezone.now() + timedelta(days=1)
        )
        cancelled = services.cancel_reservation(bot=provisioned_bot, reservation_id=reservation.public_id, actor=None)
        assert cancelled.status == "CANCELLED"


class TestCommerceConversation:
    """The full customer-facing flow, through the real dispatcher."""

    @pytest.fixture
    def commerce_bot(self, catalogue, tenant_a, user, pool_entry, fake_transport):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug="generic", platforms=["telegram"],
            feature_slugs=["product_catalog", "cart_orders"],
            currency="USD", business_draft={"name": "Generic Shop"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

        job = run_job(create_job(order=order, strategy="pool"))
        assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"
        return job.bot

    @pytest.fixture
    def restaurant_bot(self, catalogue, tenant_a, user, pool_entry, fake_transport):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug="restaurant", platforms=["telegram"],
            feature_slugs=["table_reservation"],
            currency="USD", business_draft={"name": "Generic Diner"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})

        job = run_job(create_job(order=order, strategy="pool"))
        assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"
        bot = job.bot
        WorkingHours.objects.create(
            tenant=bot.tenant, bot=bot, weekday=dj_timezone.now().weekday(), opens_at=time(0, 0), closes_at=time(23, 59)
        )
        WorkingHours.objects.create(
            tenant=bot.tenant, bot=bot, weekday=(dj_timezone.now().weekday() + 1) % 7,
            opens_at=time(0, 0), closes_at=time(23, 59),
        )
        return bot

    def _dispatch(self, instance, payload):
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate

        update = InboundUpdate.objects.create(
            instance=instance, platform_update_id=payload["update_id"], raw=payload
        )
        return dispatch_update(update)

    def _message(self, update_id, text, user_id="777"):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id, "text": text, "chat": {"id": 1},
                "from": {"id": int(user_id), "first_name": "Ada", "username": "ada", "language_code": "en"},
            },
        }

    def _callback_from(self, sent, label: str) -> str:
        buttons = sent.payload["reply_markup"]["inline_keyboard"]
        return next(b["callback_data"] for row in buttons for b in row if b["text"] == label)

    def _last_sent(self, instance):
        from apps.bot_runtime.models import OutboundMessage

        return OutboundMessage.objects.filter(instance=instance).latest("created_at")

    def _tap(self, instance, update_id, payload):
        return self._dispatch(instance, {
            "update_id": update_id,
            "callback_query": {
                "id": "cb", "data": payload,
                "from": {"id": 777, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        })

    def test_browse_add_to_cart_and_checkout(self, commerce_bot, fake_transport):
        instance = commerce_bot.instances.get(platform="telegram")
        product = services.create_product(bot=commerce_bot, actor=None, name="Latte", price_minor=450)

        self._dispatch(instance, self._message(1, "/catalog"))
        pick_product = self._callback_from(self._last_sent(instance), f"{product.name} — $4.50")
        detail = self._tap(instance, 2, pick_product)
        assert detail.route == "product_catalog:product"

        add = self._callback_from(self._last_sent(instance), "Add to cart")
        added = self._tap(instance, 3, add)
        assert product.name in added.reply_text

        self._dispatch(instance, self._message(4, "/cart"))
        checkout_cb = self._callback_from(self._last_sent(instance), "Checkout")
        result = self._tap(instance, 5, checkout_cb)

        assert result.route == "cart_orders:checkout"
        assert BusinessOrder.objects.filter(bot=commerce_bot).count() == 1

    def test_a_bot_with_only_product_catalog_does_not_offer_add_to_cart(self, catalogue, tenant_a, user, pool_entry, fake_transport):
        from apps.orders.domain.state_machine import Actor, OrderStatus
        from apps.orders.services import build_quote, claim_quote, place_order, transition_order
        from apps.provisioning.saga import create_job, run_job

        quote, _ = build_quote(
            template_slug="generic", platforms=["telegram"], feature_slugs=["product_catalog"],
            currency="USD", business_draft={"name": "Browse Only"},
        )
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        order = place_order(quote=quote, tenant=tenant_a, user=user)
        for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
            actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
            transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})
        job = run_job(create_job(order=order, strategy="pool"))
        bot = job.bot

        instance = bot.instances.get(platform="telegram")
        services.create_product(bot=bot, actor=None, name="Poster", price_minor=1200)

        self._dispatch(instance, self._message(1, "/catalog"))
        pick_product = self._callback_from(self._last_sent(instance), "Poster — $12.00")
        self._tap(instance, 2, pick_product)

        sent = self._last_sent(instance)
        assert sent.payload["reply_markup"] is None

    def test_table_reservation_end_to_end(self, restaurant_bot, fake_transport):
        instance = restaurant_bot.instances.get(platform="telegram")

        self._dispatch(instance, self._message(1, "/reserve"))
        pick_size = self._callback_from(self._last_sent(instance), "2")
        step2 = self._tap(instance, 2, pick_size)
        assert step2.route == "table_reservation:pick_time"

        time_message = self._last_sent(instance)
        first_time_label = time_message.payload["reply_markup"]["inline_keyboard"][0][0]["text"]
        pick_time = self._callback_from(time_message, first_time_label)
        result = self._tap(instance, 3, pick_time)

        assert TableReservation.objects.filter(bot=restaurant_bot, party_size=2).count() == 1
        assert "2" in result.reply_text


class TestCommerceApi:
    def test_category_and_product_crud(self, auth_client, provisioned_bot):
        cat = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/product-categories/", {"name": "Drinks"}, format="json"
        )
        assert cat.status_code == 201
        category_id = cat.json()["id"]

        create = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/products/",
            {"name": "Latte", "price_minor": 450, "category_id": category_id}, format="json",
        )
        assert create.status_code == 201
        product_id = create.json()["id"]

        updated = auth_client.patch(
            f"/api/v1/bots/{provisioned_bot.public_id}/products/{product_id}/",
            {"name": "Cappuccino"}, format="json",
        )
        assert updated.status_code == 200 and updated.json()["name"] == "Cappuccino"

        deleted = auth_client.delete(f"/api/v1/bots/{provisioned_bot.public_id}/products/{product_id}/")
        assert deleted.status_code == 204

    def test_orders_list_and_cancel(self, auth_client, provisioned_bot, contact, product):
        cart = services.get_or_create_cart(provisioned_bot, contact)
        services.add_to_cart(cart=cart, product=product)
        order = services.checkout(cart=cart)

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/business-orders/")
        assert listed.status_code == 200
        assert any(o["id"] == str(order.public_id) for o in listed.json())

        cancelled = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/business-orders/{order.public_id}/cancel/"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"

    def test_table_reservations_list_and_cancel(self, auth_client, provisioned_bot, contact):
        reservation = services.reserve_table(
            bot=provisioned_bot, contact=contact, party_size=3, starts_at=dj_timezone.now() + timedelta(days=1)
        )

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/table-reservations/")
        assert listed.status_code == 200
        assert any(r["id"] == str(reservation.public_id) for r in listed.json())

        cancelled = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/table-reservations/{reservation.public_id}/cancel/"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"

    def test_a_stranger_cannot_manage_another_tenants_products(self, other_client, provisioned_bot):
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/products/")
        assert response.status_code == 404


def _test_image(name: str = "photo.png") -> "SimpleUploadedFile":
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class TestPropertyListings:
    """Real estate's dedicated data model (Phase 10.5) — a `Product` has no bedrooms,
    listing type, or address, which is the whole reason this isn't just `create_product`
    with extra kwargs."""

    def test_create_requires_a_title(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_property(
                bot=provisioned_bot, actor=None, title=" ", listing_type="SALE",
                property_type="APARTMENT", price_minor=100,
            )

    def test_create_and_read_back_the_fields_that_dont_exist_on_product(self, provisioned_bot):
        listing = services.create_property(
            bot=provisioned_bot, actor=None, title="2-bed downtown", listing_type="RENT",
            property_type="APARTMENT", price_minor=250_000_00, bedrooms=2, bathrooms=1,
            area_sqm=85, address="12 Example Street",
        )
        assert listing.bedrooms == 2
        assert listing.area_sqm == 85
        assert listing.listing_type == "RENT"

    def test_update_and_delete(self, provisioned_bot):
        listing = services.create_property(
            bot=provisioned_bot, actor=None, title="House", listing_type="SALE",
            property_type="HOUSE", price_minor=100,
        )
        updated = services.update_property(bot=provisioned_bot, property_id=listing.pk, actor=None, bedrooms=4)
        assert updated.bedrooms == 4

        services.delete_property(bot=provisioned_bot, property_id=listing.pk, actor=None)
        assert services.list_properties(provisioned_bot.pk) == []

    def test_add_and_delete_an_image(self, provisioned_bot):
        listing = services.create_property(
            bot=provisioned_bot, actor=None, title="House", listing_type="SALE",
            property_type="HOUSE", price_minor=100,
        )
        image = services.add_property_image(
            bot=provisioned_bot, property_id=listing.pk, actor=None, upload=_test_image()
        )
        assert image.file.name.startswith("public/properties/")

        services.delete_property_image(bot=provisioned_bot, image_id=image.pk, actor=None)
        assert listing.images.count() == 0

    def test_the_management_api_full_round_trip(self, auth_client, provisioned_bot):
        create = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/properties/",
            {
                "title": "Garden house", "listing_type": "SALE", "property_type": "HOUSE",
                "price_minor": 500_000_00, "bedrooms": 3,
            },
            format="json",
        )
        assert create.status_code == 201, create.json()
        property_id = create.json()["id"]

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/properties/")
        assert any(p["id"] == property_id for p in listed.json())

        updated = auth_client.patch(
            f"/api/v1/bots/{provisioned_bot.public_id}/properties/{property_id}/",
            {"bedrooms": 5}, format="json",
        )
        assert updated.json()["bedrooms"] == 5

        image_upload = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/properties/{property_id}/images/",
            {"file": _test_image()}, format="multipart",
        )
        assert image_upload.status_code == 201
        assert image_upload.json()["url"].startswith("/media/public/properties/")

        deleted = auth_client.delete(f"/api/v1/bots/{provisioned_bot.public_id}/properties/{property_id}/")
        assert deleted.status_code == 204

    def test_a_stranger_cannot_manage_another_tenants_properties(self, other_client, provisioned_bot):
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/properties/")
        assert response.status_code == 404


class TestCourseOfferings:
    """Academy's dedicated data model (Phase 10.5) — schedule, instructor and
    capacity/enrollment have no home on a generic `Product` either."""

    def test_create_requires_a_title(self, provisioned_bot):
        with pytest.raises(ValidationError):
            services.create_course(bot=provisioned_bot, actor=None, title=" ", price_minor=100)

    def test_capacity_defaults_to_unlimited(self, provisioned_bot):
        course = services.create_course(bot=provisioned_bot, actor=None, title="Photoshop", price_minor=100)
        assert course.capacity is None
        assert course.has_capacity is True

    def test_update_and_delete(self, provisioned_bot):
        course = services.create_course(bot=provisioned_bot, actor=None, title="Excel", price_minor=100)
        updated = services.update_course(
            bot=provisioned_bot, course_id=course.pk, actor=None, instructor_name="Dana"
        )
        assert updated.instructor_name == "Dana"

        services.delete_course(bot=provisioned_bot, course_id=course.pk, actor=None)
        assert services.list_courses(provisioned_bot.pk) == []

    def test_set_thumbnail_replaces_any_existing_one(self, provisioned_bot):
        course = services.create_course(bot=provisioned_bot, actor=None, title="Excel", price_minor=100)
        first = services.set_course_thumbnail(
            bot=provisioned_bot, course_id=course.pk, actor=None, upload=_test_image("a.png")
        )
        first_name = first.thumbnail.name
        second = services.set_course_thumbnail(
            bot=provisioned_bot, course_id=course.pk, actor=None, upload=_test_image("b.png")
        )
        assert second.thumbnail.name != first_name

    def test_the_management_api_full_round_trip(self, auth_client, provisioned_bot):
        create = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/courses/",
            {"title": "Beginner Photoshop", "price_minor": 199_00, "instructor_name": "Dana"},
            format="json",
        )
        assert create.status_code == 201, create.json()
        course_id = create.json()["id"]

        thumb = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/courses/{course_id}/thumbnail/",
            {"file": _test_image()}, format="multipart",
        )
        assert thumb.status_code == 200
        assert thumb.json()["thumbnail_url"].startswith("/media/public/courses/")

        deleted = auth_client.delete(f"/api/v1/bots/{provisioned_bot.public_id}/courses/{course_id}/")
        assert deleted.status_code == 204

    def test_a_stranger_cannot_manage_another_tenants_courses(self, other_client, provisioned_bot):
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/courses/")
        assert response.status_code == 404


class TestProductPhotos:
    """The general-purpose extension of the same upload pipeline (Phase 10.5) — a
    shop/restaurant product had no image field at all until now."""

    def test_add_and_delete_an_image(self, provisioned_bot, product):
        image = services.add_product_image(
            bot=provisioned_bot, product_id=product.pk, actor=None, upload=_test_image()
        )
        assert image.file.name.startswith("public/products/")

        services.delete_product_image(bot=provisioned_bot, image_id=image.pk, actor=None)
        assert product.images.count() == 0

    def test_the_management_api_round_trip(self, auth_client, provisioned_bot, product):
        upload = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/products/{product.pk}/images/",
            {"file": _test_image()}, format="multipart",
        )
        assert upload.status_code == 201
        image_id = upload.json()["id"]
        assert upload.json()["url"].startswith("/media/public/products/")

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/products/")
        product_row = next(p for p in listed.json() if p["id"] == product.pk)
        assert len(product_row["images"]) == 1

        deleted = auth_client.delete(f"/api/v1/bots/{provisioned_bot.public_id}/product-images/{image_id}/")
        assert deleted.status_code == 204
