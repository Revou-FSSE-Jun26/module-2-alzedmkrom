"""Tests for the User endpoints (`users_bp` in routes.py): register, login,
and get-by-id. Covers happy path and error cases per endpoint.

Registration stays public. Login now returns a token pair rather than the
bare user, and get-by-id is restricted to the account holder or an admin, so
those sections assert the new shapes. JWT behaviour itself (refresh,
rotation, logout, revocation, expiry) lives in test_auth.py.
"""


def _register(client, username="alice", email="alice@example.com", password="hunter2pass", role=None):
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
    _register(client, email="alice@example.com", password="hunter2pass")

    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "hunter2pass"})

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
    _register(client, email="alice@example.com", password="hunter2pass")

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
    _register(client, email="alice@example.com", password="hunter2pass")

    wrong_password = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "nope"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.get_json() == unknown_email.get_json()


def test_login_rejects_deactivated_account(client, make_user):
    make_user(username="banned", email="banned@example.com", password="hunter2pass", is_active=False)

    resp = client.post("/auth/login", json={"email": "banned@example.com", "password": "hunter2pass"})

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


# ---------------------------------------------------------------------------
# Password policy on POST /users
# ---------------------------------------------------------------------------
#
# The rule: at least 8 characters, at least one letter, at least one digit.
# No uppercase character is required, but passwords stay case-sensitive.
# Enforced on registration only — see `_password_policy_error` in routes.py
# for why login must not re-check it.


def test_register_rejects_password_under_minimum_length(client):
    resp = _register(client, password="abc1234")  # 7 characters

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "weak_password"
    assert "8 characters" in body["message"]


def test_register_accepts_password_at_exactly_minimum_length(client):
    resp = _register(client, password="abcdefg1")  # 8 characters

    assert resp.status_code == 201


def test_register_rejects_password_without_a_digit(client):
    resp = _register(client, password="onlyletters")

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "weak_password"
    assert "number" in body["message"]


def test_register_rejects_password_without_a_letter(client):
    resp = _register(client, password="12345678")

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "weak_password"
    assert "letter" in body["message"]


def test_register_does_not_require_an_uppercase_letter(client):
    resp = _register(client, password="alllowercase1")

    assert resp.status_code == 201


def test_register_allows_uppercase_and_symbols(client):
    resp = _register(client, password="Passw0rd!#$")

    assert resp.status_code == 201


def test_register_rejects_whitespace_only_password(client):
    resp = _register(client, password="        ")  # 8 spaces: long enough, no letter/digit

    assert resp.status_code == 400


def test_register_counts_length_on_the_raw_password(client):
    """Spaces are real characters, so they count toward the minimum."""
    resp = _register(client, password="  a1  ")  # 6 raw characters

    assert resp.status_code == 400
    assert "8 characters" in resp.get_json()["message"]


def test_register_reports_only_the_rule_that_failed(client):
    """A short password is not also lectured about digits it already has."""
    resp = _register(client, password="abc1")

    message = resp.get_json()["message"]
    assert "8 characters" in message
    assert "number" not in message


def test_register_error_precedence_blank_before_policy(client):
    """An empty password is 'cannot be empty', not 'too short'."""
    resp = _register(client, password="")

    assert resp.status_code == 400
    assert "empty" in resp.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Passwords are case-sensitive
# ---------------------------------------------------------------------------


def test_password_is_case_sensitive_on_login(client):
    """No uppercase is *required*, but case still has to match exactly."""
    _register(client, email="case@example.com", password="Secret123")

    wrong_case = client.post(
        "/auth/login", json={"email": "case@example.com", "password": "secret123"}
    )
    assert wrong_case.status_code == 401
    assert wrong_case.get_json()["code"] == "invalid_credentials"

    exact = client.post(
        "/auth/login", json={"email": "case@example.com", "password": "Secret123"}
    )
    assert exact.status_code == 200


def test_password_case_variants_are_distinct_accounts(client):
    """Two accounts may hold passwords differing only in case."""
    _register(client, username="lower", email="lower@example.com", password="secret123")
    _register(client, username="upper", email="upper@example.com", password="SECRET123")

    assert client.post(
        "/auth/login", json={"email": "lower@example.com", "password": "secret123"}
    ).status_code == 200
    assert client.post(
        "/auth/login", json={"email": "upper@example.com", "password": "secret123"}
    ).status_code == 401


def test_login_does_not_enforce_the_password_policy(client, make_user):
    """An account whose password predates the policy can still log in."""
    make_user(username="legacy", email="legacy@example.com", password="old")

    resp = client.post(
        "/auth/login", json={"email": "legacy@example.com", "password": "old"}
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unicode normalisation
# ---------------------------------------------------------------------------
#
# The same visible password can arrive encoded more than one way depending on
# keyboard, OS, or paste buffer. Without normalisation the two hash
# differently, and the owner is locked out by a password that looks correct on
# screen. See `normalize_password` in models.py.

# "café1234", composed (é as U+00E9) and decomposed (e + combining acute).
_PRECOMPOSED = "caf\u00e91234"
_DECOMPOSED = "cafe\u03011234"


def test_the_two_encodings_are_different_strings():
    """Guards the premise: if these were equal the tests below prove nothing."""
    assert _PRECOMPOSED != _DECOMPOSED
    assert len(_PRECOMPOSED) == 8
    assert len(_DECOMPOSED) == 9


def test_login_accepts_the_other_encoding_of_the_same_password(client):
    _register(client, email="cafe@example.com", password=_PRECOMPOSED)

    resp = client.post(
        "/auth/login", json={"email": "cafe@example.com", "password": _DECOMPOSED}
    )

    assert resp.status_code == 200


def test_login_works_when_registration_used_the_decomposed_form(client):
    """Normalisation has to apply on the way in as well as the way out."""
    _register(client, email="cafe2@example.com", password=_DECOMPOSED)

    resp = client.post(
        "/auth/login", json={"email": "cafe2@example.com", "password": _PRECOMPOSED}
    )

    assert resp.status_code == 200


def test_normalisation_does_not_fold_case(client):
    """Normalising must not quietly make passwords case-insensitive."""
    _register(client, email="nofold@example.com", password="Secret123")

    assert client.post(
        "/auth/login", json={"email": "nofold@example.com", "password": "secret123"}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "nofold@example.com", "password": "Secret123"}
    ).status_code == 200


def test_decomposed_password_is_measured_after_normalising(client):
    """9 raw characters, 8 after normalising: the rule applies to the 8."""
    resp = _register(client, email="len@example.com", password=_DECOMPOSED)

    assert resp.status_code == 201


def test_compatibility_folding_makes_a_superscript_count_as_its_digit(client):
    """NFKC turns '²' into '2', so it satisfies the digit rule as a real digit."""
    resp = _register(client, email="sup@example.com", password="password\u00b2")

    assert resp.status_code == 201
    # And the folded form is what was stored, so the plain digit logs in too.
    assert client.post(
        "/auth/login", json={"email": "sup@example.com", "password": "password2"}
    ).status_code == 200


def test_non_ascii_letters_are_accepted(client):
    """CJK characters count as letters, so this is 8 characters with a digit."""
    password = "\u5bc6\u7801\u5bc6\u78011234"
    assert len(password) == 8

    resp = _register(client, email="cjk@example.com", password=password)

    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Maximum password length
# ---------------------------------------------------------------------------


def test_register_rejects_password_over_maximum_length(client, app):
    too_long = "a1" + ("x" * app.config["PASSWORD_MAX_LENGTH"])

    resp = _register(client, password=too_long)

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "weak_password"
    assert str(app.config["PASSWORD_MAX_LENGTH"]) in body["message"]


def test_register_accepts_password_at_exactly_maximum_length(client, app):
    maximum = app.config["PASSWORD_MAX_LENGTH"]
    exact = "a1" + ("x" * (maximum - 2))
    assert len(exact) == maximum

    resp = _register(client, password=exact)

    assert resp.status_code == 201


def test_maximum_is_measured_after_normalising(client, app):
    """A decomposed password that shrinks under the limit is accepted."""
    maximum = app.config["PASSWORD_MAX_LENGTH"]
    # One combining pair per two characters, so the raw string is longer than
    # the limit while the normalised form lands exactly on it.
    over_the_raw_limit = "a1" + ("e\u0301" * (maximum - 2))
    assert len(over_the_raw_limit) > maximum

    resp = _register(client, password=over_the_raw_limit)

    # Normalises to `maximum` characters, so length is fine.
    assert resp.status_code == 201


def test_long_password_still_fits_the_hash_column(client, app):
    """The stored hash is fixed-width, so the column is not what bounds input."""
    from extensions import db
    from models import User

    maximum = app.config["PASSWORD_MAX_LENGTH"]
    created = _register(
        client, email="longpw@example.com", password="a1" + ("x" * (maximum - 2))
    )
    assert created.status_code == 201

    user = db.session.get(User, created.get_json()["id"])
    assert len(user.password_hash) <= 255
