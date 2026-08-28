"""Tests for the User endpoints (`users_bp` in routes.py): register, login,
and get-by-id. Covers happy path and error cases per endpoint."""


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


def test_register_user_with_explicit_role_happy_path(client):
    resp = _register(client, role="ADMIN")

    assert resp.status_code == 201
    assert resp.get_json()["role"] == "ADMIN"


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


def test_login_happy_path(client):
    _register(client, email="alice@example.com", password="hunter2")

    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "hunter2"})

    assert resp.status_code == 200
    assert resp.get_json()["email"] == "alice@example.com"


def test_login_missing_body_error(client):
    resp = client.post("/auth/login", data="not json", content_type="text/plain")

    assert resp.status_code == 400


def test_login_missing_credentials_error(client):
    resp = client.post("/auth/login", json={"email": "alice@example.com"})

    assert resp.status_code == 400
    assert "required" in resp.get_json()["message"]


def test_login_wrong_password_error(client):
    _register(client, email="alice@example.com", password="hunter2")

    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong"})

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


def test_login_unknown_email_error(client):
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


# ---------------------------------------------------------------------------
# GET /<id>
# ---------------------------------------------------------------------------


def test_get_user_happy_path(client):
    created = _register(client).get_json()

    resp = client.get(f"/users/{created['id']}")

    assert resp.status_code == 200
    assert resp.get_json()["username"] == "alice"


def test_get_user_not_found_error(client):
    resp = client.get("/users/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"
