"""Application configuration."""

import os

from dotenv import load_dotenv

# Loads .env into the process environment. python-dotenv never overrides a
# variable already set (e.g. by the real shell/host env in production), so
# this is safe to call unconditionally.
load_dotenv()


class Config:
    """Configuration loaded with app.config.from_object(Config).

    Every value below is read from the environment (populated from `.env`
    for local development). There is no hardcoded fallback for
    `SQLALCHEMY_DATABASE_URI` or `SECRET_KEY`: a missing `.env` now fails
    loudly at startup instead of silently connecting to the wrong database
    or signing sessions with a well-known dev key.
    """

    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]

    # Separate connection string used only by database migrations (Alembic /
    # `flask db *`). Supabase's transaction-mode pooler (port 6543) that
    # `DATABASE_URL` points at cannot run migration DDL transactions, so
    # migrations must go through the session-mode pooler (port 5432) named
    # here. Falls back to DATABASE_URL when unset, so a plain local Postgres
    # setup with only DATABASE_URL still works. See migrations/env.py.
    DIRECT_URL = os.environ.get("DIRECT_URL", os.environ["DATABASE_URL"])

    # Turn off Flask-SQLAlchemy's event tracking to avoid its overhead warning.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ["SECRET_KEY"]

    # Parsed from the string env vars always are; anything other than a
    # literal "true" (case-insensitive) is treated as False.
    DEBUG = os.environ.get("FLASK_DEBUG", "false").strip().lower() == "true"

    # Browser origins allowed to call this API cross-origin (see extensions.py).
    # Without these headers a browser blocks every request from a frontend on a
    # different origin, even though the API itself answers correctly — curl and
    # Postman are unaffected, which is why this is easy to miss.
    #
    # Comma-separated. The default covers the usual local frontend dev servers
    # (Create React App / Next.js on 3000, Vite on 5173). Set `CORS_ORIGINS` in
    # the environment to the deployed frontend's origin in production, e.g.
    #   CORS_ORIGINS=https://my-shop.vercel.app,http://localhost:5173
    #
    # An explicit allowlist is used rather than "*" because this API has no
    # authentication yet: any origin permitted here can place orders and create
    # users. Widen it deliberately, not by default.
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,"
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
