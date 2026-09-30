"""Tests for the `flask set-password` CLI command (cli.py).

The command exists for the two things the API deliberately cannot do: give a
working password to an account that has none (every `seed.sql` account stores
placeholder text rather than a real hash, so it rejects every password), and
create the first administrator (`POST /users` ignores a caller-supplied role
unless the request already carries an admin token, so the first one has to come
from somewhere already trusted).

Both paths are checked end-to-end here: after the command runs, the account is
asked to actually log in through `POST /auth/login`.
"""

import pytest

from extensions import db
from models import User


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture()
def unusable_account(app):
    """An account whose password_hash is placeholder text, as seed.sql leaves it."""
    user = User(
        username="budi_santoso",
        email="budi@mail.com",
        password_hash="hash_budi_001",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# The seeded-account case
# ---------------------------------------------------------------------------


def test_placeholder_hash_cannot_log_in_to_begin_with(client, unusable_account):
    """Establishes the starting state the command is there to fix."""
    assert _login(client, "budi@mail.com", "hash_budi_001").status_code == 401
    assert _login(client, "budi@mail.com", "anything").status_code == 401


def test_set_password_makes_a_seeded_account_usable(runner, client, unusable_account):
    result = runner.invoke(
        args=["set-password", "budi@mail.com", "--password", "shopper2026"]
    )

    assert result.exit_code == 0, result.output
    assert "Password set for budi@mail.com" in result.output
    assert "could not log in at all" in result.output  # notes the previous state

    db.session.expire_all()
    assert _login(client, "budi@mail.com", "shopper2026").status_code == 200


def test_set_password_replaces_an_existing_working_password(runner, client, make_user):
    make_user(username="alice", email="alice@example.com", password="hunter2pass")

    result = runner.invoke(
        args=["set-password", "alice@example.com", "--password", "brandnew123"]
    )

    assert result.exit_code == 0
    # The "had no usable password" note must NOT appear for this account.
    assert "could not log in at all" not in result.output

    db.session.expire_all()
    assert _login(client, "alice@example.com", "brandnew123").status_code == 200
    assert _login(client, "alice@example.com", "hunter2pass").status_code == 401


# ---------------------------------------------------------------------------
# The first-administrator case
# ---------------------------------------------------------------------------


def test_set_password_can_promote_to_admin(runner, client, make_user):
    user_id = make_user(username="boss", email="boss@example.com")

    result = runner.invoke(
        args=[
            "set-password", "boss@example.com",
            "--password", "bosspass123",
            "--role", "ADMIN",
        ]
    )

    assert result.exit_code == 0
    assert "CUSTOMER -> ADMIN" in result.output

    db.session.expire_all()
    assert db.session.get(User, user_id).role == "ADMIN"

    # And the promoted account can now reach an admin-only endpoint.
    token = _login(client, "boss@example.com", "bosspass123").get_json()["access_token"]
    created = client.post(
        "/categories",
        json={"name": "Electronics"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201


def test_role_is_left_alone_when_not_given(runner, make_user):
    user_id = make_user(username="plain", email="plain@example.com", role="CUSTOMER")

    runner.invoke(args=["set-password", "plain@example.com", "--password", "plain12345"])

    db.session.expire_all()
    assert db.session.get(User, user_id).role == "CUSTOMER"


def test_blank_role_is_rejected(runner, make_user):
    make_user(username="plain", email="plain@example.com")

    result = runner.invoke(
        args=["set-password", "plain@example.com", "--password", "plain12345",
              "--role", "   "]
    )

    assert result.exit_code == 1
    assert "Role cannot be blank" in result.output


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_email_fails_clearly(runner, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(args=["set-password", "nobody@example.com",
                                 "--password", "whatever123"])

    assert result.exit_code == 1
    assert "No account found" in result.output
    # Being a trusted shell, it may list what does exist.
    assert "alice@example.com" in result.output


def test_email_lookup_is_case_insensitive(runner, client, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(args=["set-password", "ALICE@EXAMPLE.COM",
                                 "--password", "newpass123"])

    assert result.exit_code == 0
    db.session.expire_all()
    assert _login(client, "alice@example.com", "newpass123").status_code == 200


def test_weak_password_is_rejected_by_default(runner, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(args=["set-password", "alice@example.com",
                                 "--password", "short1"])

    assert result.exit_code == 1
    assert "at least 8 characters" in result.output
    assert "--allow-weak" in result.output


def test_password_without_a_digit_is_rejected(runner, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(args=["set-password", "alice@example.com",
                                 "--password", "onlyletters"])

    assert result.exit_code == 1
    assert "number" in result.output


def test_allow_weak_bypasses_the_policy(runner, client, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(args=["set-password", "alice@example.com",
                                 "--password", "abc", "--allow-weak"])

    assert result.exit_code == 0
    db.session.expire_all()
    # Login never enforces the policy, so the weak password works.
    assert _login(client, "alice@example.com", "abc").status_code == 200


def test_empty_password_is_rejected_even_with_allow_weak(runner, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(args=["set-password", "alice@example.com",
                                 "--password", "   ", "--allow-weak"])

    assert result.exit_code == 1
    assert "cannot be empty" in result.output


# ---------------------------------------------------------------------------
# The password must not leak into output
# ---------------------------------------------------------------------------


def test_the_password_is_never_echoed(runner, make_user):
    make_user(username="alice", email="alice@example.com")
    secret = "verysecret123"

    result = runner.invoke(args=["set-password", "alice@example.com",
                                 "--password", secret])

    assert result.exit_code == 0
    assert secret not in result.output


def test_prompted_password_is_hidden_and_confirmed(runner, client, make_user):
    """Without --password the value is prompted for twice and not shown."""
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(
        args=["set-password", "alice@example.com"],
        input="prompted123\nprompted123\n",
    )

    assert result.exit_code == 0, result.output
    assert "prompted123" not in result.output

    db.session.expire_all()
    assert _login(client, "alice@example.com", "prompted123").status_code == 200


def test_mismatched_confirmation_is_rejected(runner, make_user):
    make_user(username="alice", email="alice@example.com")

    result = runner.invoke(
        args=["set-password", "alice@example.com"],
        input="first12345\nsecond12345\nthird12345\nthird12345\n",
    )

    # Click re-prompts on a mismatch; the run still ends up succeeding with the
    # value that was entered twice, having complained in between.
    assert "do not match" in result.output.lower()


# ---------------------------------------------------------------------------
# Normalisation applies here too
# ---------------------------------------------------------------------------


def test_cli_set_password_normalises_unicode(runner, client, make_user):
    """A password set here verifies against either encoding, as via the API."""
    make_user(username="cafe", email="cafe@example.com")
    precomposed = "caf\u00e91234"
    decomposed = "cafe\u03011234"

    result = runner.invoke(args=["set-password", "cafe@example.com",
                                 "--password", precomposed])
    assert result.exit_code == 0

    db.session.expire_all()
    assert _login(client, "cafe@example.com", decomposed).status_code == 200
