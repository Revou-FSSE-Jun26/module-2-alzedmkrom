"""Tests for the JWT layer: /auth/me, /auth/refresh, /auth/logout, and the
token lifecycle behaviours those depend on.

Covers the parts that are easy to get subtly wrong and impossible to see from
a happy-path login:

  * **rotation** — refreshing invalidates the refresh token just used, so a
    replayed one is refused
  * **revocation** — logout really does stop a token that has not expired yet
  * **expiry** — an expired *access* token is recoverable (refresh and retry),
    an expired *refresh* token is the session ending, and the two are
    distinguishable by the response alone
  * **account state** — deactivating an account immediately invalidates tokens
    already issued to it

Token lifetimes here are forced per-test with `expires_delta` rather than by
waiting, so the expiry paths are exercised without slow tests.
"""

from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token, create_refresh_token

from extensions import db
from models import TokenBlocklist, User


def _login(client, email, password="hunter2"):
    """Register nothing; log in an existing account and return the body."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tokens(client, make_user):
    """A real login, returning the token pair plus the account's id."""
    user_id = make_user(username="alice", email="alice@example.com", password="hunter2")
    body = _login(client, "alice@example.com")
    return {
        "user_id": user_id,
        "access": body["access_token"],
        "refresh": body["refresh_token"],
    }


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


def test_me_returns_the_token_owner(client, tokens):
    resp = client.get("/auth/me", headers=_bearer(tokens["access"]))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == tokens["user_id"]
    assert body["email"] == "alice@example.com"
    assert "password_hash" not in body


def test_me_requires_a_token(client):
    resp = client.get("/auth/me")

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "authorization_required"


def test_me_rejects_a_refresh_token(client, tokens):
    """The refresh token is only good at /auth/refresh."""
    resp = client.get("/auth/me", headers=_bearer(tokens["refresh"]))

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "token_invalid"


def test_me_rejects_a_garbage_token(client):
    resp = client.get("/auth/me", headers=_bearer("clearly-not-a-jwt"))

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "token_invalid"


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


def test_refresh_issues_a_new_pair(client, tokens):
    resp = client.post("/auth/refresh", headers=_bearer(tokens["refresh"]))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["access_token"] and body["access_token"] != tokens["access"]
    assert body["refresh_token"] and body["refresh_token"] != tokens["refresh"]
    assert body["user"]["id"] == tokens["user_id"]


def test_refreshed_access_token_works(client, tokens):
    refreshed = client.post("/auth/refresh", headers=_bearer(tokens["refresh"])).get_json()

    resp = client.get("/auth/me", headers=_bearer(refreshed["access_token"]))

    assert resp.status_code == 200


def test_refresh_rejects_an_access_token(client, tokens):
    resp = client.post("/auth/refresh", headers=_bearer(tokens["access"]))

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "token_invalid"


def test_refresh_requires_a_token(client):
    resp = client.post("/auth/refresh")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rotation: the refresh token used is single-use
# ---------------------------------------------------------------------------


def test_refresh_revokes_the_token_it_consumed(client, tokens):
    first = client.post("/auth/refresh", headers=_bearer(tokens["refresh"]))
    assert first.status_code == 200

    replay = client.post("/auth/refresh", headers=_bearer(tokens["refresh"]))

    assert replay.status_code == 401
    assert replay.get_json()["code"] == "token_revoked"


def test_rotation_chain_keeps_working(client, tokens):
    """Each refresh hands over a usable successor, so an active session slides."""
    current = tokens["refresh"]
    for _ in range(3):
        body = client.post("/auth/refresh", headers=_bearer(current)).get_json()
        assert body["refresh_token"] != current
        current = body["refresh_token"]

    assert client.get("/auth/me", headers=_bearer(body["access_token"])).status_code == 200


def test_refresh_records_the_revocation(client, tokens, app):
    client.post("/auth/refresh", headers=_bearer(tokens["refresh"]))

    with app.app_context():
        rows = db.session.query(TokenBlocklist).all()
        assert len(rows) == 1
        assert rows[0].token_type == "refresh"
        assert rows[0].user_id == tokens["user_id"]


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


def test_logout_revokes_the_access_token(client, tokens):
    logout = client.post("/auth/logout", headers=_bearer(tokens["access"]))

    assert logout.status_code == 200
    assert logout.get_json()["revoked"]["access"] is True

    after = client.get("/auth/me", headers=_bearer(tokens["access"]))
    assert after.status_code == 401
    assert after.get_json()["code"] == "token_revoked"


def test_logout_also_revokes_the_refresh_token_when_given(client, tokens):
    logout = client.post(
        "/auth/logout",
        headers=_bearer(tokens["access"]),
        json={"refresh_token": tokens["refresh"]},
    )

    assert logout.status_code == 200
    assert logout.get_json()["revoked"] == {"access": True, "refresh": True}

    # The session is genuinely over: the refresh token cannot mint a new access token.
    after = client.post("/auth/refresh", headers=_bearer(tokens["refresh"]))
    assert after.status_code == 401
    assert after.get_json()["code"] == "token_revoked"


def test_logout_without_refresh_token_leaves_the_session_refreshable(client, tokens):
    """Documents why a client should send the refresh token on logout."""
    client.post("/auth/logout", headers=_bearer(tokens["access"]))

    still_valid = client.post("/auth/refresh", headers=_bearer(tokens["refresh"]))

    assert still_valid.status_code == 200


def test_logout_ignores_a_malformed_refresh_token(client, tokens):
    resp = client.post(
        "/auth/logout",
        headers=_bearer(tokens["access"]),
        json={"refresh_token": "not-a-jwt"},
    )

    assert resp.status_code == 200
    assert resp.get_json()["revoked"] == {"access": True, "refresh": False}


def test_logout_cannot_revoke_another_users_refresh_token(client, make_user, app):
    victim_id = make_user(username="victim", email="victim@example.com", password="hunter2")
    attacker_id = make_user(username="attacker", email="attacker@example.com", password="hunter2")

    victim = _login(client, "victim@example.com")
    attacker = _login(client, "attacker@example.com")

    resp = client.post(
        "/auth/logout",
        headers=_bearer(attacker["access_token"]),
        json={"refresh_token": victim["refresh_token"]},
    )

    assert resp.status_code == 200
    assert resp.get_json()["revoked"]["refresh"] is False

    # The victim's session is untouched.
    assert client.post(
        "/auth/refresh", headers=_bearer(victim["refresh_token"])
    ).status_code == 200


def test_logout_requires_a_token(client):
    resp = client.post("/auth/logout")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Expiry: access token recoverable, refresh token terminal
# ---------------------------------------------------------------------------


def test_expired_access_token_is_reported_as_recoverable(client, app, make_user):
    user_id = make_user(username="alice", email="alice@example.com")
    with app.app_context():
        user = db.session.get(User, user_id)
        stale = create_access_token(identity=user, expires_delta=timedelta(seconds=-1))

    resp = client.get("/auth/me", headers=_bearer(stale))

    assert resp.status_code == 401
    body = resp.get_json()
    assert body["code"] == "token_expired"
    assert body["token_type"] == "access"
    assert "refresh" in body["message"].lower()


def test_expired_refresh_token_ends_the_session(client, app, make_user):
    """The auto-logout: an idle session's refresh token lapses and cannot be renewed."""
    user_id = make_user(username="alice", email="alice@example.com")
    with app.app_context():
        user = db.session.get(User, user_id)
        stale = create_refresh_token(identity=user, expires_delta=timedelta(seconds=-1))

    resp = client.post("/auth/refresh", headers=_bearer(stale))

    assert resp.status_code == 401
    body = resp.get_json()
    assert body["code"] == "token_expired"
    assert body["token_type"] == "refresh"
    assert "log in again" in body["message"].lower()


def test_expired_access_token_can_be_replaced_via_refresh(client, app, tokens):
    """End-to-end recovery: expired access token -> refresh -> request succeeds."""
    with app.app_context():
        user = db.session.get(User, tokens["user_id"])
        stale = create_access_token(identity=user, expires_delta=timedelta(seconds=-1))

    assert client.get("/auth/me", headers=_bearer(stale)).status_code == 401

    refreshed = client.post("/auth/refresh", headers=_bearer(tokens["refresh"])).get_json()

    assert client.get(
        "/auth/me", headers=_bearer(refreshed["access_token"])
    ).status_code == 200


# ---------------------------------------------------------------------------
# Account state overrides an already-issued token
# ---------------------------------------------------------------------------


# These three mutate the account through `db.session` directly rather than
# inside a nested `with app.app_context()`. The `app` fixture holds a single
# app context open for the whole test, and the test client's requests reuse
# it, so they share that context's SQLAlchemy session. A nested context gets
# its own session: its commit reaches the database, but the outer session
# keeps returning the copy it already has in its identity map, and the change
# appears not to have happened. Writing through the same session the request
# will use avoids that, and still exercises what these tests are about —
# `auth._user_lookup` re-reading the account on every request instead of
# trusting what the token says.


def test_deactivating_an_account_invalidates_its_live_token(client, tokens):
    assert client.get("/auth/me", headers=_bearer(tokens["access"])).status_code == 200

    db.session.get(User, tokens["user_id"]).is_active = False
    db.session.commit()

    resp = client.get("/auth/me", headers=_bearer(tokens["access"]))

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "user_unavailable"


def test_deleting_an_account_invalidates_its_live_token(client, tokens):
    db.session.delete(db.session.get(User, tokens["user_id"]))
    db.session.commit()

    resp = client.get("/auth/me", headers=_bearer(tokens["access"]))

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "user_unavailable"


def test_promoting_a_user_takes_effect_on_the_existing_token(client, tokens):
    """Role is re-read from the database, not trusted from the token claim."""
    denied = client.post("/categories", json={"name": "Electronics"},
                         headers=_bearer(tokens["access"]))
    assert denied.status_code == 403

    db.session.get(User, tokens["user_id"]).role = "ADMIN"
    db.session.commit()

    allowed = client.post("/categories", json={"name": "Electronics"},
                          headers=_bearer(tokens["access"]))
    assert allowed.status_code == 201
