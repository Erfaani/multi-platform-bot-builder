"""Throttling is disabled for the rest of the suite, so it gets its own tests here.

Without these, "all tests pass" would be compatible with rate limiting being broken
in production (SECURITY.md §8).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

AUTH_RATE_LIMIT = 3


@pytest.fixture
def throttled(monkeypatch):
    """Re-enable a low auth rate limit for one test.

    Patches ``THROTTLE_RATES`` directly rather than using ``override_settings``:
    DRF binds that attribute on the class at import time, so a settings override
    never reaches it and the test would silently prove nothing.
    """
    rates = {**SimpleRateThrottle.THROTTLE_RATES, "auth": f"{AUTH_RATE_LIMIT}/min"}
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", rates)
    cache.clear()
    yield
    cache.clear()


def test_login_attempts_are_rate_limited(api, throttled, user):
    """Brute-forcing a password must hit a wall well before it succeeds."""
    payload = {"email": user.email, "password": "wrong-password"}

    statuses = [
        api.post("/api/v1/auth/login/", payload, format="json").status_code
        for _ in range(AUTH_RATE_LIMIT + 2)
    ]

    assert statuses[:AUTH_RATE_LIMIT] == [401] * AUTH_RATE_LIMIT
    assert statuses[-1] == 429


def test_throttled_response_uses_the_standard_error_shape(api, throttled, user):
    payload = {"email": user.email, "password": "wrong-password"}
    for _ in range(AUTH_RATE_LIMIT + 1):
        response = api.post("/api/v1/auth/login/", payload, format="json")

    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == "error.throttled"
    # Clients need to know how long to wait, not just that they failed.
    assert "Retry-After" in response
    assert int(response["Retry-After"]) > 0
