"""Browse, cart, checkout, and table reservation (spec's commerce module).

Stateless throughout, same convention as `appointments` and `faq:list`: every step is a
signed callback carrying its own accumulated selections, never `session.state`. Nothing
here is free text, so there is nothing a state handler would buy over this.

Route namespaces match *feature slugs*, not app or menu names — `product_catalog:*`,
`cart_orders:*`, `table_reservation:*`. A sub-route with no manifest `menu` entry (every
one below `catalog`/`cart`/`reserve` itself) falls back to
`apps.bot_runtime.router.owning_feature`, which takes the string before the route's
first `:` as the feature slug. "commerce" and "restaurant" are this app's and this
template's names, not features — using them here silently denies every tap (see
PHASES.md's Phase 7 write-up for the same mistake, made and fixed once already, in
`apps.crm`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from apps.bot_runtime.handlers import HandlerResult, command, route
from apps.core.errors import AppError
from apps.core.formatting import money_to_representation
from apps.core.money import Money
from apps.platforms.base import Choice, Reply

from apps.commerce import services
from apps.commerce.models import Product

MAX_TIME_CHOICES = 12
PARTY_SIZES = (1, 2, 3, 4, 5, 6)


def _menu_choices(ctx) -> list[Choice]:
    from apps.features.registry import manifests_for

    entries = sorted(
        (entry for manifest in manifests_for(ctx.enabled_features) for entry in manifest.menu),
        key=lambda entry: entry.sort_order,
    )
    return [Choice(label_key=entry.label_key, value=entry.route) for entry in entries]


def _menu_reply(ctx, text_key: str, **params) -> HandlerResult:
    return HandlerResult(reply=Reply(text_key=text_key, params=params, choices=_menu_choices(ctx)), next_state="IDLE")


def _bot_and_contact(ctx, event):
    from apps.bots.models import Bot
    from apps.bot_runtime.models import BusinessContact

    bot = Bot.objects.select_related("tenant").get(pk=ctx.bot_id)
    contact = BusinessContact.objects.get(
        bot_id=ctx.bot_id, platform=ctx.platform, platform_user_id=event.user_ref
    )
    return bot, contact


def _money_label(amount_minor: int, currency: str) -> str:
    return money_to_representation(Money(amount_minor, currency), locale="en")["formatted"]


# --------------------------------------------------------------------------- catalogue


@route("commerce:catalog")
@command("catalog")
def browse_catalog(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    categories = services.list_categories(ctx.bot_id)
    if categories:
        return HandlerResult(
            reply=Reply(
                text_key="bot.commerce.select_category",
                choices=[
                    Choice(label_key=f"literal:{c.name}", value=f"product_catalog:category.{c.pk}")
                    for c in categories
                ],
            ),
            next_state="IDLE",
        )
    return _list_products(ctx, category_id=None)


@route("product_catalog:category")
def browse_category(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not value.isdigit():
        return _menu_reply(ctx, "bot.commerce.expired")
    return _list_products(ctx, category_id=int(value))


def _list_products(ctx, *, category_id: int | None) -> HandlerResult:
    products = services.list_products(ctx.bot_id, category_id=category_id)
    if not products:
        return _menu_reply(ctx, "bot.commerce.no_products")

    return HandlerResult(
        reply=Reply(
            text_key="bot.commerce.select_category",
            choices=[
                Choice(
                    label_key=f"literal:{p.name} — {_money_label(p.price_minor, p.currency)}",
                    value=f"product_catalog:product.{p.pk}",
                )
                for p in products
            ],
        ),
        next_state="IDLE",
    )


@route("product_catalog:product")
def product_detail(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    product = Product.objects.filter(bot_id=ctx.bot_id, pk=value, is_active=True).first()
    if product is None:
        return _menu_reply(ctx, "bot.commerce.expired")

    choices = []
    if ctx.has_feature("cart_orders"):
        choices.append(Choice(label_key="bot.commerce.add_to_cart", value=f"cart_orders:add.{product.pk}"))

    return HandlerResult(
        reply=Reply(
            text_key="bot.commerce.product_detail",
            params={
                "name": product.name,
                "description": product.description,
                "price": _money_label(product.price_minor, product.currency),
            },
            choices=choices,
        ),
        next_state="IDLE",
    )


# --------------------------------------------------------------------------- cart


@route("cart_orders:add")
def add_to_cart(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    product = Product.objects.filter(bot_id=ctx.bot_id, pk=value, is_active=True).first()
    if product is None:
        return _menu_reply(ctx, "bot.commerce.expired")

    bot, contact = _bot_and_contact(ctx, event)
    cart = services.get_or_create_cart(bot, contact)
    try:
        services.add_to_cart(cart=cart, product=product)
    except AppError:
        return _menu_reply(ctx, "bot.commerce.out_of_stock")

    return HandlerResult(
        reply=Reply(
            text_key="bot.commerce.added_to_cart",
            params={"name": product.name},
            choices=[Choice(label_key="menu.cart", value="commerce:cart"), *_menu_choices(ctx)],
        ),
        next_state="IDLE",
    )


@route("commerce:cart")
@command("cart")
def view_cart(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    bot, contact = _bot_and_contact(ctx, event)
    cart = services.get_or_create_cart(bot, contact)
    items = services.cart_items(cart)

    if not items:
        return _menu_reply(ctx, "bot.commerce.empty_cart")

    lines = "\n".join(
        f"{item.quantity} x {item.product.name} — {_money_label(item.product.price_minor * item.quantity, item.product.currency)}"
        for item in items
    )
    total = _money_label(services.cart_total_minor(cart), items[0].product.currency)

    return HandlerResult(
        reply=Reply(
            text_key="bot.commerce.cart_summary",
            params={"items": lines, "total": total},
            choices=[Choice(label_key="bot.commerce.checkout", value="cart_orders:checkout")],
        ),
        next_state="IDLE",
    )


@route("cart_orders:checkout")
def checkout(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    bot, contact = _bot_and_contact(ctx, event)
    cart = services.get_or_create_cart(bot, contact)

    try:
        services.checkout(cart=cart)
    except AppError:
        return _menu_reply(ctx, "bot.commerce.empty_cart")

    return _menu_reply(ctx, "bot.commerce.order_placed")


# --------------------------------------------------------------------------- table reservation


@route("restaurant:reserve")
@command("reserve")
def start_reservation(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    return HandlerResult(
        reply=Reply(
            text_key="bot.restaurant.select_party_size",
            choices=[
                Choice(label_key=f"literal:{n}", value=f"table_reservation:pick_time.{n}") for n in PARTY_SIZES
            ],
        ),
        next_state="IDLE",
    )


@route("table_reservation:pick_time")
def pick_time(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not value.isdigit():
        return _menu_reply(ctx, "bot.commerce.expired")
    party_size = int(value)

    tz = ZoneInfo(ctx.timezone or "UTC")
    today = datetime.now(tz).date()

    found: list[datetime] = []
    for offset in range(services.RESERVATION_WINDOW_DAYS + 1):
        day = today + timedelta(days=offset)
        found.extend(services.available_times(bot_id=ctx.bot_id, timezone=ctx.timezone, day=day))
        if len(found) >= MAX_TIME_CHOICES:
            break

    if not found:
        return _menu_reply(ctx, "bot.commerce.no_availability")

    choices = [
        Choice(
            label_key=f"literal:{slot.astimezone(tz).strftime('%a %b %d, %H:%M')}",
            value=f"table_reservation:confirm.{party_size}:{int(slot.timestamp() // 60)}",
        )
        for slot in found[:MAX_TIME_CHOICES]
    ]
    return HandlerResult(
        reply=Reply(text_key="bot.restaurant.select_time", choices=choices), next_state="IDLE"
    )


@route("table_reservation:confirm")
def confirm_reservation(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    party_size_str, _, epoch_minutes = value.partition(":")
    if not party_size_str.isdigit() or not epoch_minutes.isdigit():
        return _menu_reply(ctx, "bot.commerce.expired")

    starts_at = datetime.fromtimestamp(int(epoch_minutes) * 60, tz=dt_timezone.utc)
    bot, contact = _bot_and_contact(ctx, event)

    try:
        reservation = services.reserve_table(
            bot=bot, contact=contact, party_size=int(party_size_str), starts_at=starts_at
        )
    except AppError:
        return _menu_reply(ctx, "bot.restaurant.slot_taken")

    tz = ZoneInfo(ctx.timezone or "UTC")
    local = reservation.starts_at.astimezone(tz)
    return _menu_reply(
        ctx,
        "bot.restaurant.reserved",
        party_size=str(reservation.party_size),
        date=local.strftime("%Y-%m-%d"),
        time=local.strftime("%H:%M"),
    )
