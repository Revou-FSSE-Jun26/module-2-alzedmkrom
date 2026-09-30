"""Tests for request rate limiting (the limiter in extensions.py).

The point of these limits is anti-brute-force, not capacity: every role check
in auth.py is worthless once somebody guesses an admin's password, and guessing
is only expensive if attempts are capped. So the tests below care most about
`POST /auth/login` — that failed attempts are counted, that the cap actually
stops them, and that the refusal is distinguishable from a wrong password.

Rate limiting is off for the rest of the suite (see conftest.py), so every test
here asks for the `rate_limited` fixture, which enables it with empty counters.
Limits are overridden per test to small numbers, so a test needs a handful of
requests rather than a hundred, and does not silently change meaning if the
configured defaults are edited.
"""

import pytest

from extensions import db
from models import User


@pytest.fixture()
def account(make_user):
    """An existing account to aim login attempts at."""
    make_user(username="target", email="target@example.com", password="hunter2pass")
    return "target@example.com"


def _login(client, email, password="hunter2pass", ip="203.0.113.10"):
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
        environ_base={"REMOTE_ADDR": ip},
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


def test_login_blocks_repeated_wrong_passwords(client, app, account, rate_limited):
    """The brute-force case: failed attempts count toward the limit."""
    app.config["RATELIMIT_LOGIN"] = "3 per minute"

    for attempt in range(3):
        resp = _login(client, account, password=f"wrong{attempt}")
        assert resp.status_code == 401, f"attempt {attempt} should be a normal rejection"

    blocked = _login(client, account, password="wrong-again")

    assert blocked.status_code == 429
    assert blocked.get_json()["code"] == "rate_limit_exceeded"


def test_blocked_even_with_the_correct_password(client, app, account, rate_limited):
    """Once the limit trips, the right password does not get through either.

    Otherwise an attacker's final successful guess would still be rewarded.
    """
    app.config["RATELIMIT_LOGIN"] = "2 per minute"

    _login(client, account, password="wrong")
    _login(client, account, password="wrong")

    resp = _login(client, account)  # correct password

    assert resp.status_code == 429


def test_rate_limited_response_is_json_with_the_shared_envelope(
    client, app, account, rate_limited
):
    app.config["RATELIMIT_LOGIN"] = "1 per minute"
    _login(client, account, password="wrong")

    resp = _login(client, account, password="wrong")

    assert resp.status_code == 429
    assert "application/json" in resp.headers.get("Content-Type", "")
    body = resp.get_json()
    assert body["error"] == "Too Many Requests"
    assert body["code"] == "rate_limit_exceeded"
    assert body["message"]
    assert "limit" in body  # which limit tripped, for debugging


def test_rate_limited_response_says_when_to_retry(client, app, account, rate_limited):
    app.config["RATELIMIT_LOGIN"] = "1 per minute"
    _login(client, account, password="wrong")

    resp = _login(client, account, password="wrong")

    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") is not None


def test_a_429_is_distinguishable_from_a_wrong_password(
    client, app, account, rate_limited
):
    """A client must be able to tell "slow down" from "bad credentials"."""
    app.config["RATELIMIT_LOGIN"] = "1 per minute"

    rejected = _login(client, account, password="wrong")
    throttled = _login(client, account, password="wrong")

    assert rejected.status_code == 401
    assert rejected.get_json()["code"] == "invalid_credentials"
    assert throttled.status_code == 429
    assert throttled.get_json()["code"] == "rate_limit_exceeded"


def test_limits_are_tracked_per_client_address(client, app, account, rate_limited):
    """One attacker being throttled must not lock out everybody else."""
    app.config["RATELIMIT_LOGIN"] = "2 per minute"

    for _ in range(3):
        _login(client, account, password="wrong", ip="203.0.113.10")
    assert _login(client, account, ip="203.0.113.10").status_code == 429

    # A different address still has its full budget, and can log in.
    other = _login(client, account, ip="198.51.100.20")
    assert other.status_code == 200


def test_budget_is_reported_in_headers(client, app, account, rate_limited):
    app.config["RATELIMIT_LOGIN"] = "5 per minute"

    resp = _login(client, account)

    assert resp.status_code == 200
    assert resp.headers.get("X-RateLimit-Limit") is not None
    assert resp.headers.get("X-RateLimit-Remaining") is not None


# ---------------------------------------------------------------------------
# POST /users
# ---------------------------------------------------------------------------


def test_registration_is_rate_limited(client, app, rate_limited):
    """Stops a script filling the users table."""
    app.config["RATELIMIT_REGISTER"] = "2 per minute"

    created = 0
    for index in range(2):
        resp = client.post(
            "/users",
            json={
                "username": f"spam{index}",
                "email": f"spam{index}@example.com",
                "password": "hunter2pass",
            },
            environ_base={"REMOTE_ADDR": "203.0.113.30"},
        )
        assert resp.status_code == 201
        created += 1

    blocked = client.post(
        "/users",
        json={
            "username": "spam99",
            "email": "spam99@example.com",
            "password": "hunter2pass",
        },
        environ_base={"REMOTE_ADDR": "203.0.113.30"},
    )

    assert blocked.status_code == 429
    assert db.session.query(User).filter(User.username.like("spam%")).count() == created


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


def test_refresh_is_rate_limited(client, app, account, rate_limited):
    app.config["RATELIMIT_LOGIN"] = "100 per minute"
    app.config["RATELIMIT_REFRESH"] = "2 per minute"

    refresh_token = _login(client, account).get_json()["refresh_token"]

    first = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
        environ_base={"REMOTE_ADDR": "203.0.113.40"},
    )
    assert first.status_code == 200
    rotated = first.get_json()["refresh_token"]

    second = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {rotated}"},
        environ_base={"REMOTE_ADDR": "203.0.113.40"},
    )
    assert second.status_code == 200

    third = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {second.get_json()['refresh_token']}"},
        environ_base={"REMOTE_ADDR": "203.0.113.40"},
    )
    assert third.status_code == 429


# ---------------------------------------------------------------------------
# Public reads, and the off switch
# ---------------------------------------------------------------------------


def test_catalogue_reads_are_not_throttled_at_login_rates(client, app, rate_limited):
    """Browsing has to stay usable; only the credential path is tight."""
    app.config["RATELIMIT_LOGIN"] = "1 per minute"

    for _ in range(20):
        assert client.get("/products").status_code == 200


def test_limits_can_be_disabled(client, app, account, rate_limited):
    """`RATELIMIT_ENABLED=false` is what makes load testing possible."""
    app.config["RATELIMIT_LOGIN"] = "1 per minute"
    rate_limited.enabled = False

    for _ in range(5):
        assert _login(client, account, password="wrong").status_code == 401
