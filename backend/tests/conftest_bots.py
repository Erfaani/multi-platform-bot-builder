"""Shared Phase 4 fixtures: fake platform transport, pool stock, provisioned bots.

Imported by `conftest.py` so every test can use them.
"""

from __future__ import annotations

import pytest

from apps.platforms.transport import FakeTransport, override_transport

DEFAULT_BOT_ID = "7000000001"
DEFAULT_USERNAME = "demo_clinic_bot"


#: Tokens registered by tests, mapped to the identity the platform would report.
#: Keyed by the numeric prefix of the token, which is how real tokens encode bot id.
TOKEN_IDENTITIES: dict[str, tuple[str, str]] = {
    "7100000001": ("dual_clinic_tg_bot", "Dual Clinic"),
    "7200000001": ("dual_clinic_bale_bot", "Dual Clinic"),
}


def _identity_for(token: str) -> dict:
    """Return a per-token identity, as a real Bot API would.

    A fake that answers `getMe` identically for every token would let a bug where one
    instance overwrites another's username pass unnoticed — precisely the bug a
    multi-platform test exists to catch.
    """
    bot_id = (token.split(":", 1)[0] or DEFAULT_BOT_ID).strip()
    username, name = TOKEN_IDENTITIES.get(bot_id, (DEFAULT_USERNAME, "Demo Clinic"))
    return {"id": int(bot_id), "username": username, "first_name": name}


def telegram_responses() -> dict:
    """The happy-path Bot API surface that provisioning and the gateway touch."""
    return {
        "getMe": lambda payload, token: _identity_for(token),
        "setMyName": True,
        "setMyDescription": True,
        "setMyShortDescription": True,
        "setMyCommands": True,
        "setWebhook": True,
        "deleteWebhook": True,
        "sendMessage": lambda payload, token: {
            "message_id": 1,
            "chat": {"id": payload.get("chat_id")},
        },
        "answerCallbackQuery": True,
    }


@pytest.fixture
def fake_transport():
    """Install a fake platform transport for the duration of a test.

    Nothing in the suite may touch a real bot API — the conformance suite runs on
    recorded fixtures (BOT_RUNTIME.md §8).
    """
    transport = FakeTransport(responses=telegram_responses())
    override_transport(transport)
    yield transport
    override_transport(None)


@pytest.fixture
def pool_entry(db, fake_transport):
    """One available Telegram bot in the pool."""
    from apps.bots.credentials import add_pool_entry

    entry = add_pool_entry(
        platform="telegram",
        username=DEFAULT_USERNAME,
        token=f"{DEFAULT_BOT_ID}:AA-pool-token-aaaaaaaaaaaaaaaaaaaaaaaa",
    )
    entry.platform_bot_id = DEFAULT_BOT_ID
    entry.save(update_fields=["platform_bot_id"])
    return entry


@pytest.fixture
def paid_order(catalogue, tenant_a, user, db):
    """An order that has reached PAID, ready for provisioning."""
    from apps.orders.domain.state_machine import Actor, OrderStatus
    from apps.orders.services import build_quote, claim_quote, place_order, transition_order

    quote, _ = build_quote(
        template_slug="clinic",
        platforms=["telegram"],
        feature_slugs=["faq", "contact"],
        currency="USD",
        business_draft={
            "name": "Tehran Smile Clinic",
            "description": "A friendly dental clinic.",
            "phone": "+98 21 1234 5678",
            "email": "hello@clinic.example",
            "address": "12 Example Street",
        },
    )
    claim_quote(quote=quote, tenant=tenant_a, user=user)
    order = place_order(quote=quote, tenant=tenant_a, user=user)

    for target in (
        OrderStatus.RECEIPT_SUBMITTED,
        OrderStatus.PAYMENT_REVIEW,
        OrderStatus.PAID,
    ):
        actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
        transition_order(
            order=order,
            target=target,
            actor_type=actor,
            user=user,
            scopes={"*"},
            reason="test fixture",
        )
    order.refresh_from_db()
    return order


@pytest.fixture
def provisioned_bot(paid_order, pool_entry, fake_transport):
    """A fully provisioned, ACTIVE bot with a live instance."""
    from apps.provisioning.saga import create_job, run_job

    job = create_job(order=paid_order, strategy="pool")
    job = run_job(job)
    assert job.status == "SUCCEEDED", f"{job.error_code}: {job.error_detail}"

    job.refresh_from_db()
    return job.bot


@pytest.fixture
def active_instance(provisioned_bot):
    return provisioned_bot.instances.get(platform="telegram")
