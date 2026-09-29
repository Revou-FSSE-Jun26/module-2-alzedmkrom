"""Application configuration."""

import os
from datetime import timedelta

from dotenv import load_dotenv

# Loads .env into the process environment. python-dotenv never overrides a
# variable already set (e.g. by the real shell/host env in production), so
# this is safe to call unconditionally.
load_dotenv()


def _positive_int_env(name: str, default: int) -> int:
    """Read `name` as a positive integer, falling back to `default`.

    A blank, non-numeric, or non-positive value falls back rather than
    raising, so a typo in a deployment environment variable cannot produce a
    token lifetime of zero (which would reject every request immediately) or
    crash the app at import time.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


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

    # -- JWT authentication -------------------------------------------------
    # Signing key for tokens. Kept separate from `SECRET_KEY` so the token
    # signing key can be rotated (invalidating every outstanding token)
    # without also invalidating anything else signed with `SECRET_KEY`.
    # Falls back to `SECRET_KEY` when unset, so no extra variable is required
    # for the app to boot.
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "").strip() or os.environ["SECRET_KEY"]

    # Tokens are read from the `Authorization: Bearer <token>` header only.
    # Cookies are deliberately not enabled: this API is called cross-origin by
    # a browser frontend, and cookie-based JWT would need CSRF protection and
    # `supports_credentials` on the CORS config to work safely.
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"

    # Access token lifetime. Short by design: an access token cannot be
    # revoked cheaply on every request, so a small window limits how long a
    # leaked one is useful. The frontend is expected to treat a
    # `token_expired` 401 as "silently call POST /auth/refresh and retry".
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=_positive_int_env("JWT_ACCESS_MINUTES", 15)
    )

    # Refresh token lifetime, and with refresh-token rotation this is
    # effectively the *idle* timeout that produces the auto-logout: every
    # successful POST /auth/refresh issues a new refresh token and revokes
    # the one just used, so an actively-used session keeps sliding forward
    # while an idle one eventually expires and forces a fresh login.
    # Default 7 days (10080 minutes). Set to e.g. 30 for a 30-minute idle
    # window.
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        minutes=_positive_int_env("JWT_REFRESH_MINUTES", 60 * 24 * 7)
    )

    # Checked by the blocklist loader in auth.py. Both token types are
    # checked so that logout can revoke the refresh token (ending the
    # session) and the access token (ending the current request window).
    JWT_BLOCKLIST_ENABLED = True
    JWT_BLOCKLIST_TOKEN_CHECKS = ["access", "refresh"]

    # Role name that unlocks the admin-only endpoints (product/category
    # writes, order status changes). Compared case-insensitively against
    # `users.role`, whose server default is 'CUSTOMER'.
    ADMIN_ROLE = os.environ.get("ADMIN_ROLE", "ADMIN").strip() or "ADMIN"
