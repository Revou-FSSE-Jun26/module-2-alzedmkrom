"""Pytest fixtures shared across the test suite.

Forces `DATABASE_URL` to a throwaway SQLite file *before* any project module
is imported, so the test suite never touches the real `revoshop_db`. This
has to happen before the first import of `extensions` (directly, or
transitively through `app`/`routes`/`models`), because `config.py` reads
`os.environ["DATABASE_URL"]` once, at import time, and `python-dotenv`'s
`load_dotenv()` never overrides an environment variable that is already set.

Each test gets a fresh schema: `db.create_all()` before, `db.drop_all()`
after, so no row from one test can leak into another.

Authentication fixtures
-----------------------
Most endpoints now require a JWT (see `auth.py`), so the fixtures below
provide pre-authenticated clients:

    client           anonymous, for public routes and 401 checks
    customer_client  signed in as a CUSTOMER
    admin_client     signed in as an ADMIN

`customer_client` and `admin_client` are ordinary Flask test clients that
attach `Authorization: Bearer <token>` to every request, so a test that needs
authentication differs from one that does not only by which fixture it asks
for. A test can still override the header per request (to check a bad token,
say) because the injection uses `setdefault`.
"""

import os
import tempfile

import pytest
from flask.testing import FlaskClient
from sqlalchemy import event

_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".sqlite")
os.close(_TEST_DB_FD)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
# At least 32 bytes, so HS256 token signing does not emit
# InsecureKeyLengthWarning on every test that mints a token.
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["FLASK_DEBUG"] = "false"

# Importing `app` (the entry point, not `extensions`) is what registers the
# blueprints, the error handlers, and the JWT callbacks, matching how the real
# server starts up.
import app as _app_entry  # noqa: E402,F401
from flask_jwt_extended import create_access_token, create_refresh_token  # noqa: E402

from extensions import app as flask_app, db  # noqa: E402
from models import Category, User  # noqa: E402,F401

# SQLite ignores foreign-key constraints (including ON DELETE RESTRICT)
# unless this pragma is set per-connection. schema.sql's RESTRICT
# constraints, which delete_category/delete_product rely on, would silently
# no-op in tests without this.
with flask_app.app_context():
    event.listen(
        db.engine,
        "connect",
        lambda dbapi_connection, connection_record: dbapi_connection.execute(
            "PRAGMA foreign_keys=ON"
        ),
    )


class _TokenClient(FlaskClient):
    """Test client that sends a bearer token unless the test supplies its own."""

    token = None

    def open(self, *args, **kwargs):
        if self.token:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("Authorization", f"Bearer {self.token}")
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)


@pytest.fixture()
def app():
    """Function-scoped Flask app with a clean schema for every test."""
    flask_app.config.update(TESTING=True)
    flask_app.test_client_class = _TokenClient
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """Anonymous Flask test client bound to the per-test app above."""
    return app.test_client()


@pytest.fixture()
def make_user(app):
    """Factory creating a user row directly, returning its id.

    Bypasses `POST /users` on purpose: that route refuses to honor a
    caller-supplied `role`, so an admin cannot be created through it without
    already having an admin token — a chicken-and-egg problem for the fixtures.
    """

    def _make(
        username="someone",
        email=None,
        password="hunter2",
        role="CUSTOMER",
        is_active=True,
    ):
        with app.app_context():
            user = User(
                username=username,
                email=email or f"{username}@example.com",
                role=role,
                is_active=is_active,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            return user.id

    return _make


def _authorized_client(app, user_id, refresh=False):
    """Build a test client carrying a token minted for `user_id`."""
    with app.app_context():
        user = db.session.get(User, user_id)
        if refresh:
            token = create_refresh_token(identity=user)
        else:
            token = create_access_token(
                identity=user, additional_claims={"role": user.role}
            )
    client = app.test_client()
    client.token = token
    return client


@pytest.fixture()
def customer_user(make_user):
    """Id of a plain CUSTOMER account."""
    return make_user(username="customer", email="customer@example.com")


@pytest.fixture()
def admin_user(make_user):
    """Id of an ADMIN account."""
    return make_user(username="admin", email="admin@example.com", role="ADMIN")


@pytest.fixture()
def customer_client(app, customer_user):
    """Client authenticated as `customer_user` with an access token."""
    return _authorized_client(app, customer_user)


@pytest.fixture()
def admin_client(app, admin_user):
    """Client authenticated as `admin_user` with an access token."""
    return _authorized_client(app, admin_user)


@pytest.fixture()
def authorized_client_for(app):
    """Factory for a client authenticated as an arbitrary user id.

    Used by tests that need a *second* account, e.g. proving one customer
    cannot read another customer's order.
    """

    def _for(user_id, refresh=False):
        return _authorized_client(app, user_id, refresh=refresh)

    return _for


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db_file():
    """Remove the throwaway SQLite file once the whole test session ends."""
    yield
    with flask_app.app_context():
        db.engine.dispose()
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass
