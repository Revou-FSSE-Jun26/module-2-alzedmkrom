"""Tests for the User endpoints (`users_bp` in routes.py): register, login,
and get-by-id. Covers happy path and error cases per endpoint.

Registration stays public. Login now returns a token pair rather than the
bare user, and get-by-id is restricted to the account holder or an admin, so
those sections assert the new shapes. JWT behaviour itself (refresh,
rotation, logout, revocation, expiry) lives in test_auth.py.
"""


def _register(client, username="alice", email="alice@example.com", password="hunter2", role=None):
    body = {"username": username, "email": email, "password": password}
    if role is not None:
        body["role"] = role
    return client.post("/users", json=body)


# ---------------------------------------------------------------------------
# POST /users (register)
# ---------------------------------------------------------------------------


def test_register_user_happy_path(client):
    resp = _register(client)

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["role"] == "CUSTOMER"
    assert "password" not in body
    assert "password_hash" not in body


def test_register_user_ignores_self_assigned_role(client):
    """An anonymous signup cannot make itself an admin."""
    resp = _register(client, role="ADMIN")

    assert resp.status_code == 201
    assert resp.get_json()["role"] == "CUSTOMER"


def test_register_user_role_honored_for_admin_caller(admin_client):
    resp = _register(admin_client, username="colleague", email="colleague@example.com", role="ADMIN")

    assert resp.status_code == 201
    assert resp.get_json()["role"] == "ADMIN"


def test_register_user_ignores_role_for_customer_caller(customer_client):
    resp = _register(customer_client, username="sneaky", email="sneaky@example.com", role="ADMIN")

    assert resp.status_code == 201
    assert resp.get_json()["role"] == "CUSTOMER"


def test_register_user_missing_body_error(client):
    resp = client.post("/users", data="not json", content_type="text/plain")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_register_user_blank_username_error(client):
    resp = _register(client, username="   ")

    assert resp.status_code == 400
    assert "Username" in resp.get_json()["message"]


def test_register_user_blank_email_error(client):
    resp = _register(client, email="")

    assert resp.status_code == 400
    assert "Email" in resp.get_json()["message"]


def test_register_user_blank_password_error(client):
    resp = _register(client, password="")

    assert resp.status_code == 400
    assert "Password" in resp.get_json()["message"]


def test_register_user_duplicate_email_case_insensitive_error(client):
    _register(client, username="alice", email="alice@example.com")

    resp = _register(client, username="someone_else", email="ALICE@example.com")

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "Conflict"


def test_register_user_duplicate_username_error(client):
    _register(client, username="alice", email="alice@example.com")

    resp = _register(client, username="alice", email="different@example.com")

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "Conflict"


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


def test_login_happy_path_returns_token_pair(client):
    _register(client, email="alice@example.com", password="hunter2")

    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "hunter2"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0
    assert body["refresh_expires_in"] > body["expires_in"]
    assert body["user"]["email"] == "alice@example.com"
    assert "password_hash" not in body["user"]


def test_login_missing_body_error(client):
    resp = client.post("/auth/login", data="not json", content_type="text/plain")

    assert resp.status_code == 400


def test_login_missing_credentials_error(client):
    resp = client.post("/auth/login", json={"email": "alice@example.com"})

    assert resp.status_code == 400
    assert "required" in resp.get_json()["message"]


def test_login_non_string_credentials_error(client):
    resp = client.post("/auth/login", json={"email": 123, "password": True})

    assert resp.status_code == 400


def test_login_wrong_password_error(client):
    _register(client, email="alice@example.com", password="hunter2")

    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong"})

    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"] == "Unauthorized"
    assert body["code"] == "invalid_credentials"


def test_login_unknown_email_error(client):
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "invalid_credentials"


def test_login_unknown_email_and_wrong_password_are_indistinguishable(client):
    """Neither response may reveal whether the account exists."""
    _register(client, email="alice@example.com", password="hunter2")

    wrong_password = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "nope"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.get_json() == unknown_email.get_json()


def test_login_rejects_deactivated_account(client, make_user):
    make_user(username="banned", email="banned@example.com", password="hunter2", is_active=False)

    resp = client.post("/auth/login", json={"email": "banned@example.com", "password": "hunter2"})

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "account_inactive"


# ---------------------------------------------------------------------------
# GET /users/<id>
# ---------------------------------------------------------------------------


def test_get_user_happy_path_self(customer_client, customer_user):
    resp = customer_client.get(f"/users/{customer_user}")

    assert resp.status_code == 200
    assert resp.get_json()["id"] == customer_user


def test_get_user_requires_token(client, customer_user):
    resp = client.get(f"/users/{customer_user}")

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "authorization_required"


def test_get_user_forbidden_for_other_customer(customer_client, admin_user):
    resp = customer_client.get(f"/users/{admin_user}")

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "forbidden"


def test_get_user_allowed_for_admin(admin_client, customer_user):
    resp = admin_client.get(f"/users/{customer_user}")

    assert resp.status_code == 200
    assert resp.get_json()["id"] == customer_user


def test_get_user_not_found_error_for_admin(admin_client):
    resp = admin_client.get("/users/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


def test_get_user_unknown_id_is_forbidden_not_found_for_customer(customer_client):
    """A customer probing other ids gets 403 whether or not the row exists,
    so the endpoint cannot be used to enumerate accounts."""
    resp = customer_client.get("/users/999")

    assert resp.status_code == 403
