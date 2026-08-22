"""Chat-native bot ordering (Phase 10.5's cold-start counterpart to the website
builder). Reachable only through the `bot_builder` feature's own menu entry
(`builder:start`), which is enabled on exactly one bot — the platform's own permanent
builder instance (see `apps.core.management.commands.provision_builder_bot`). Every
other route/state here is reached only *from* that entry point, so nothing needs its own
feature gate: a customer's own bot never has `bot_builder` enabled, so it can never enter
this flow (`apps.bot_runtime.router._feature_allows`).

Structurally two halves, matching the two kinds of step the website builder has:
enumerable choices (template, features — packed into signed callback values, no session
needed) and free-text collection (per-feature content, business name, email — needs
`session.context` across turns, mirroring `apps.crm.handlers`' stateful flows). Both
halves reuse the exact same domain engine the website uses
(`apps.features.manifests.CollectSchema`, `apps.orders.services.build_quote`) rather than
a parallel implementation, so a template/feature added for the website is orderable via
chat for free.

Deliberately out of scope for this pass (disclosed, not silently dropped): a customer
whose email already has a website account is asked to order from the website or link
their account first, rather than this flow guessing which account is theirs — the same
account-takeover concern `apps.customers.services.consume_link_code` already guards
against. And payment proof (a receipt photo) is uploaded on the website, not in chat —
Telegram/Bale file *download* has no existing infrastructure in this codebase
(`apps.platforms.transport` only ever POSTs JSON to the Bot API), and building it is a
separate, sizeable piece of work belonging to its own pass.
"""

from __future__ import annotations

from apps.bot_runtime.callbacks import InvalidCallback, decode
from apps.bot_runtime.handlers import HandlerResult, route, state
from apps.i18n_content.services import translate as content_translate
from apps.platforms.base import Choice, Reply

#: Every non-final step packs its payload as `builder:v.<tag>:<data>` — a single,
#: unregistered pseudo-route (never passed to `@route`) that every state handler here
#: decodes for itself, since a *state*-reached callback bypasses the router's own
#: decode-and-dispatch (`apps.bot_runtime.router.resolve`, rule 1 vs rule 3).
_CB_ROUTE = "builder:v"


def _menu_choices(ctx) -> list[Choice]:
    from apps.features.registry import manifests_for

    entries = sorted(
        (entry for manifest in manifests_for(ctx.enabled_features) for entry in manifest.menu),
        key=lambda entry: entry.sort_order,
    )
    return [Choice(label_key=entry.label_key, value=entry.route) for entry in entries]


def _bail_to_main_menu(session, ctx) -> HandlerResult:
    session.reset()
    return HandlerResult(
        reply=Reply(text_key="bot.welcome", params={"business": ctx.bot_name}, choices=_menu_choices(ctx)),
        next_state="IDLE",
    )


def _decode_value(event, ctx) -> str | None:
    """The value-half of a signed callback tap, or `None` for anything else (including
    an invalid/stale/foreign signature)."""
    if event.kind != "callback" or not event.payload.get("data"):
        return None
    try:
        _, value = decode(ctx.instance_public_id, event.payload["data"])
    except InvalidCallback:
        return None
    return value


def _tagged(value: str | None, expected_tag: str) -> str | None:
    """`"toggle:faq"` + expected_tag="toggle" -> `"faq"`. `None` if the tag doesn't
    match what this step is waiting for — a stale button from an earlier step, most
    likely, or plain string tampering."""
    if value is None or ":" not in value:
        return None
    tag, _, data = value.partition(":")
    return data if tag == expected_tag else None


def _choice(tag: str, data: str = "") -> str:
    return f"{_CB_ROUTE}.{tag}:{data}"


# --------------------------------------------------------------------------- 1. template


@route("builder:start")
def start_ordering(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    from apps.business_templates.models import BusinessTemplate

    session.reset()
    templates = list(BusinessTemplate.objects.filter(is_active=True).order_by("sort_order", "slug"))
    if not templates:
        return HandlerResult(reply=Reply(text_key="bot.builder.no_templates"), next_state="IDLE")

    choices = [
        Choice(
            label_key=f"literal:{content_translate(t, 'name', locale=locale)}",
            value=_choice("tmpl", t.slug),
        )
        for t in templates
    ]
    return HandlerResult(
        reply=Reply(text_key="bot.builder.pick_template", choices=choices),
        next_state="builder:picking_template",
    )


@state("builder:picking_template")
def picking_template(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    slug = _tagged(_decode_value(event, ctx), "tmpl")
    if slug is None:
        return start_ordering(event, session, ctx, value, locale)

    from apps.business_templates.models import BusinessTemplate

    template = BusinessTemplate.objects.filter(slug=slug, is_active=True).first()
    if template is None:
        return start_ordering(event, session, ctx, value, locale)

    return _enter_feature_selection(session, ctx, locale, template)


# --------------------------------------------------------------------------- 2. features


def _candidate_features(template, ctx) -> list:
    """Features this template offers *and* that actually work on the platform the
    customer is already chatting on — filtered up front so nothing offered here could
    ever fail `build_quote`'s own platform check later."""
    from apps.features.services import unavailable_selections

    offered = list(
        template.template_features.filter(feature__is_active=True)
        .select_related("feature")
        .order_by("sort_order")
    )
    blocked = {p.feature_slug for p in unavailable_selections([tf.feature.slug for tf in offered], [ctx.platform])}
    return [tf for tf in offered if tf.feature.slug not in blocked]


def _enter_feature_selection(session, ctx, locale: str, template) -> HandlerResult:
    candidates = _candidate_features(template, ctx)
    required = {tf.feature.slug for tf in candidates if tf.is_required}
    default = {tf.feature.slug for tf in candidates if tf.is_default or tf.is_required}

    session.set("template_slug", template.slug)
    session.set("candidate_features", [tf.feature.slug for tf in candidates])
    session.set("required_features", sorted(required))
    session.set("selected_features", sorted(default))
    return HandlerResult(reply=_feature_menu(session, ctx, locale), next_state="builder:selecting_features")


def _feature_menu(session, ctx, locale: str) -> Reply:
    from apps.features.models import Feature

    candidate_slugs = session.get("candidate_features", [])
    required = set(session.get("required_features", []))
    selected = set(session.get("selected_features", []))

    features = {f.slug: f for f in Feature.objects.filter(slug__in=candidate_slugs)}
    choices = []
    for slug in candidate_slugs:
        feature = features.get(slug)
        if feature is None or slug in required:
            continue
        mark = "✅" if slug in selected else "⬜"
        name = content_translate(feature, "name", locale=locale)
        choices.append(Choice(label_key=f"literal:{mark} {name}", value=_choice("toggle", slug)))
    choices.append(Choice(label_key="bot.builder.continue", value=_choice("continue")))

    included = ", ".join(
        content_translate(features[s], "name", locale=locale) for s in candidate_slugs if s in required and s in features
    )
    return Reply(
        text_key="bot.builder.pick_features",
        params={"included": included or "—"},
        choices=choices,
    )


@state("builder:selecting_features")
def selecting_features(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    raw = _decode_value(event, ctx)
    slug = _tagged(raw, "toggle")
    if slug is not None:
        selected = set(session.get("selected_features", []))
        if slug in selected:
            selected.discard(slug)
        else:
            selected.add(slug)
        session.set("selected_features", sorted(selected))
        return HandlerResult(reply=_feature_menu(session, ctx, locale), next_state="builder:selecting_features")

    if _tagged(raw, "continue") is not None:
        return _enter_collection_or_business_name(session, ctx, locale)

    # Anything else (stray text, a stale callback) — re-show where we are.
    return HandlerResult(reply=_feature_menu(session, ctx, locale), next_state="builder:selecting_features")


# --------------------------------------------------------------------------- 3. per-feature content


def _collect_queue(selected_slugs: list[str]) -> list[str]:
    from apps.features.registry import manifests_for

    by_slug = {m.slug: m for m in manifests_for(selected_slugs)}
    return [slug for slug in selected_slugs if by_slug.get(slug) and by_slug[slug].collects is not None]


def _enter_collection_or_business_name(session, ctx, locale: str) -> HandlerResult:
    queue = _collect_queue(session.get("selected_features", []))
    session.set("collect_queue", queue)
    session.set("collect_index", 0)
    session.set("collect_items", {})
    if not queue:
        return _ask_business_name(session, ctx)
    return _start_collecting_feature(session, ctx, locale)


def _current_schema(session):
    from apps.features.registry import get_manifest

    queue = session.get("collect_queue", [])
    index = session.get("collect_index", 0)
    if index >= len(queue):
        return None, None
    slug = queue[index]
    manifest = get_manifest(slug)
    return slug, (manifest.collects if manifest else None)


def _start_collecting_feature(session, ctx, locale: str) -> HandlerResult:
    """Enter a feature's collection at the *decision* point, not straight into its
    first field — a customer must be able to skip a feature's content entirely (the
    website's own "leave the list empty" affordance, `CollectSchema`'s own docstring)
    rather than being forced through at least one item before "done" ever appears."""
    slug, schema = _current_schema(session)
    if schema is None:
        return _ask_business_name(session, ctx)
    session.set("collect_field_index", -1)
    session.set("collect_current_item", {})
    return _item_decision_reply(session, slug, schema)


def _item_decision_reply(session, slug: str, schema) -> HandlerResult:
    count = len(session.get("collect_items", {}).get(slug, []))
    if count == 0:
        # Reuses the same schema.title_key the website shows as its step heading
        # ("How would you like to add your property listings?") rather than a
        # generic prompt of our own.
        text_key, add_key, done_key = schema.title_key, "bot.builder.addOne", "bot.builder.skipFeature"
        params = {}
    else:
        text_key, add_key, done_key = "bot.builder.item_added", "bot.builder.addAnother", "bot.builder.doneWithFeature"
        params = {"count": count}
    return HandlerResult(
        reply=Reply(
            text_key=text_key,
            params=params,
            choices=[
                Choice(label_key=add_key, value=_choice("more")),
                Choice(label_key=done_key, value=_choice("done")),
            ],
        ),
        next_state="builder:collecting",
    )


def _ask_field(session, schema) -> HandlerResult:
    field_index = session.get("collect_field_index", 0)
    field = schema.fields[field_index]
    if field.kind == "select":
        choices = [Choice(label_key=opt.label_key, value=_choice("opt", opt.value)) for opt in field.options]
        return HandlerResult(
            reply=Reply(text_key=field.label_key, choices=choices), next_state="builder:collecting"
        )
    return HandlerResult(
        reply=Reply(text_key=field.label_key, expects="text"), next_state="builder:collecting"
    )


def _finish_item_or_ask_next_field(session, schema) -> HandlerResult:
    field_index = session.get("collect_field_index", 0) + 1
    if field_index < len(schema.fields):
        session.set("collect_field_index", field_index)
        return _ask_field(session, schema)

    slug, _ = _current_schema(session)
    items = session.get("collect_items", {})
    items.setdefault(slug, []).append(session.get("collect_current_item", {}))
    session.set("collect_items", items)
    session.set("collect_current_item", {})
    session.set("collect_field_index", -1)

    return _item_decision_reply(session, slug, schema)


def _advance_to_next_feature_or_business_name(session, ctx, locale: str) -> HandlerResult:
    session.set("collect_index", session.get("collect_index", 0) + 1)
    return _start_collecting_feature(session, ctx, locale)


@state("builder:collecting")
def collecting(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    slug, schema = _current_schema(session)
    if schema is None:
        return _ask_business_name(session, ctx)

    field_index = session.get("collect_field_index", -1)

    if field_index == -1:
        raw = _decode_value(event, ctx)
        if _tagged(raw, "more") is not None:
            session.set("collect_field_index", 0)
            session.set("collect_current_item", {})
            return _ask_field(session, schema)
        if _tagged(raw, "done") is not None:
            return _advance_to_next_feature_or_business_name(session, ctx, locale)
        return _item_decision_reply(session, slug, schema)

    field = schema.fields[field_index]

    if field.kind == "select":
        raw_value = _tagged(_decode_value(event, ctx), "opt")
        if raw_value is None or raw_value not in {opt.value for opt in field.options}:
            return _ask_field(session, schema)
        text = raw_value
    else:
        text = (event.text or "").strip()
        if not text or text == "-":
            if field.required:
                return _ask_field(session, schema)
            text = ""
        text = text[: field.max_length]

    item = session.get("collect_current_item", {})
    item[field.key] = text
    session.set("collect_current_item", item)
    return _finish_item_or_ask_next_field(session, schema)


# --------------------------------------------------------------------------- 4. business name + price


def _ask_business_name(session, ctx) -> HandlerResult:
    return HandlerResult(
        reply=Reply(text_key="bot.builder.ask_business_name", expects="text"),
        next_state="builder:awaiting_business_name",
    )


@state("builder:awaiting_business_name")
def awaiting_business_name(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    name = (event.text or "").strip()
    if not name:
        return _ask_business_name(session, ctx)

    session.set("business_name", name[:255])
    return _build_and_show_quote(session, ctx, locale)


def _feature_config_from_session(session) -> dict:
    from apps.features.manifests import validate_collected_items
    from apps.features.registry import get_manifest

    cleaned = {}
    for slug, items in session.get("collect_items", {}).items():
        manifest = get_manifest(slug)
        if manifest is None or manifest.collects is None:
            continue
        valid_items = validate_collected_items(manifest.collects, items)
        if valid_items:
            cleaned[slug] = valid_items
    return cleaned


def _build_and_show_quote(session, ctx, locale: str) -> HandlerResult:
    from apps.orders.models import Quote, QuoteSource
    from apps.orders.services import build_quote

    existing_id = session.get("quote_id")
    existing = Quote.objects.filter(public_id=existing_id).first() if existing_id else None

    source = QuoteSource.BALE_BUILDER if ctx.platform == "bale" else QuoteSource.TELEGRAM_BUILDER
    quote, _auto_added = build_quote(
        quote=existing,
        template_slug=session.get("template_slug"),
        platforms=[ctx.platform],
        feature_slugs=session.get("selected_features", []),
        currency=ctx.currency,
        locale=locale,
        business_draft={
            "name": session.get("business_name", ""),
            "feature_config": _feature_config_from_session(session),
        },
        created_via=source,
    )
    session.set("quote_id", str(quote.public_id))

    from apps.core.formatting import money_to_representation
    from apps.core.money import Money

    once = money_to_representation(Money(quote.subtotal_once_minor, quote.currency), locale=locale)
    monthly = money_to_representation(Money(quote.subtotal_recurring_minor, quote.currency), locale=locale)
    total = money_to_representation(Money(quote.total_minor, quote.currency), locale=locale)

    return HandlerResult(
        reply=Reply(
            text_key="bot.builder.price_summary",
            params={
                "once": once["formatted"],
                "monthly": monthly["formatted"],
                "total": total["formatted"],
            },
            choices=[
                Choice(label_key="bot.builder.placeOrder", value=_choice("place")),
                Choice(label_key="bot.builder.cancel", value=_choice("cancel")),
            ],
        ),
        next_state="builder:reviewing_price",
    )


@state("builder:reviewing_price")
def reviewing_price(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    raw = _decode_value(event, ctx)
    if _tagged(raw, "cancel") is not None:
        return _bail_to_main_menu(session, ctx)
    if _tagged(raw, "place") is None:
        return _build_and_show_quote(session, ctx, locale)

    return HandlerResult(
        reply=Reply(text_key="bot.builder.ask_email", expects="text"),
        next_state="builder:awaiting_email",
    )


# --------------------------------------------------------------------------- 5. account + checkout


@state("builder:awaiting_email")
def awaiting_email(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    from apps.bot_builder.services import find_or_bootstrap_account, is_valid_email

    text = (event.text or "").strip()
    if not is_valid_email(text):
        return HandlerResult(
            reply=Reply(text_key="bot.builder.invalid_email", expects="text"),
            next_state="builder:awaiting_email",
        )

    from apps.core.errors import ConflictError

    try:
        user = find_or_bootstrap_account(
            email=text,
            platform=ctx.platform,
            platform_user_id=event.user_ref,
            username=event.username,
            locale=locale,
        )
    except ConflictError:
        session.reset()
        return HandlerResult(reply=Reply(text_key="bot.builder.email_taken"), next_state="IDLE")

    from apps.bot_builder.services import start_tenant_for_chat_order
    from apps.orders.models import Quote
    from apps.orders.services import claim_quote, place_order

    tenant = start_tenant_for_chat_order(user=user, business_name=session.get("business_name", ""))
    quote = Quote.objects.get(public_id=session.get("quote_id"))
    claim_quote(quote=quote, tenant=tenant, user=user)
    order = place_order(quote=quote, tenant=tenant, user=user)

    session.set("order_id", str(order.public_id))
    return _show_payment_methods(session, ctx, locale, order)


def _show_payment_methods(session, ctx, locale: str, order) -> HandlerResult:
    from apps.payments import services as payment_services

    methods = payment_services.available_methods(
        currency=order.currency, amount_minor=order.total_minor
    )
    if not methods:
        return HandlerResult(reply=Reply(text_key="bot.builder.no_payment_methods"), next_state="IDLE")

    choices = [
        Choice(label_key=f"literal:{m.name}", value=_choice("pay", str(m.pk))) for m in methods
    ]
    return HandlerResult(
        reply=Reply(text_key="bot.builder.choose_payment_method", choices=choices),
        next_state="builder:choosing_payment_method",
    )


@state("builder:choosing_payment_method")
def choosing_payment_method(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        return _bail_to_main_menu(session, ctx)

    from apps.orders.models import Order
    from apps.payments import services as payment_services
    from apps.payments.models import PaymentMethod

    method_pk = _tagged(_decode_value(event, ctx), "pay")
    order = Order.objects.select_related("tenant").filter(public_id=session.get("order_id")).first()
    if order is None:
        return _bail_to_main_menu(session, ctx)
    if method_pk is None or not method_pk.isdigit():
        return _show_payment_methods(session, ctx, locale, order)

    method = PaymentMethod.objects.filter(pk=int(method_pk), is_enabled=True).first()
    if method is None:
        return _show_payment_methods(session, ctx, locale, order)

    payment = payment_services.start_payment(order=order, method=method, user=order.placed_by)
    lines = _format_instructions(method, payment)

    from django.conf import settings

    link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/{locale}/orders/{order.public_id}"

    session.reset()
    return HandlerResult(
        reply=Reply(
            text_key="bot.builder.payment_instructions",
            params={"instructions": lines, "link": link},
        ),
        next_state="IDLE",
    )


def _format_instructions(method, payment) -> str:
    from apps.payments.providers import provider_for

    provider = provider_for(method)
    instructions = provider.instructions(method=method, payment=payment)
    lines = [instructions.headline]
    for field in instructions.fields:
        lines.append(f"{field['label']}: {field['value']}")
    for note in instructions.notes:
        lines.append(note)
    return "\n".join(lines)


# --------------------------------------------------------------------------- order status


@route("builder:status")
def order_status(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    from apps.bot_builder.services import most_recent_order_for_platform_user

    order = most_recent_order_for_platform_user(platform=ctx.platform, platform_user_id=event.user_ref)
    if order is None:
        return HandlerResult(reply=Reply(text_key="bot.builder.no_orders"), next_state="IDLE")

    return HandlerResult(
        reply=Reply(
            text_key="bot.builder.order_status",
            params={"number": order.number, "status_text": _status_text(order.status, locale)},
        ),
        next_state="IDLE",
    )


def _status_text(status: str, locale: str) -> str:
    from apps.platforms.preview.messages import translate

    return translate(f"bot.builder.orderStatus.{status}", locale=locale)
