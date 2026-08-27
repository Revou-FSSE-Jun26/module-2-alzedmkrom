"""Pytest fixtures shared across the test suite.

Forces `DATABASE_URL` to a throwaway SQLite file *before* any project module
is imported, so the test suite never touches the real `revoshop_db`. This
has to happen before the first import of `extensions` (directly, or
transitively through `app`/`routes`/`models`), because `config.py` reads
`os.environ["DATABASE_URL"]` once, at import time, and `python-dotenv`'s
`load_dotenv()` never overrides an environment variable that is already set.

Each test gets a fresh schema: `db.create_all()` before, `db.drop_all()`
after, so no row from one test can leak into another.
"""

import os
import tempfile

import pytest
from sqlalchemy import event

_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".sqlite")
os.close(_TEST_DB_FD)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["FLASK_DEBUG"] = "false"

# Importing `app` (the entry point, not `extensions`) is what registers the
# blueprints and the error handlers, matching how the real server starts up.
import app as _app_entry  # noqa: E402,F401
from extensions import app as flask_app, db  # noqa: E402
from models import Category  # noqa: E402,F401

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


@pytest.fixture()
def app():
    """Function-scoped Flask app with a clean schema for every test."""
    flask_app.config.update(TESTING=True)
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """Flask test client bound to the per-test app above."""
    return app.test_client()


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
