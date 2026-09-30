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


def _non_negative_int_env(name: str, default: int) -> int:
    """Read `name` as an integer of zero or more, falling back to `default`.

    Separate from `_positive_int_env` because zero is a meaningful value for
    some settings (no trusted proxies) rather than a mistake.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


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
    # An explicit allowlist is used rather than "*" because a permitted origin
    # can drive every endpoint the visitor's own token allows, and because "*"
    # is incompatible with ever enabling credentialed requests. Widen it
    # deliberately, not by default.
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

    # -- Password policy ----------------------------------------------------
    # Enforced by `POST /users` only (see `_password_policy_error` in
    # routes.py). Login deliberately does not re-check the policy: accounts
    # created before it existed would otherwise be locked out of their own
    # working passwords.
    #
    # The rule is length plus "at least one letter and one digit". Case is
    # not part of the rule — no uppercase character is required — but
    # passwords remain fully case-sensitive, because Werkzeug hashes the
    # exact bytes it is given and compares hashes, never the text.
    PASSWORD_MIN_LENGTH = _positive_int_env("PASSWORD_MIN_LENGTH", 8)

    # Upper bound, so the accepted input is finite rather than whatever fits in
    # a request body.
    #
    # Note that this is not dictated by `users.password_hash` being
    # VARCHAR(255): that column holds the hash, which Werkzeug's scrypt emits
    # at a fixed 162 characters no matter how long the password was. The bound
    # is for tidiness, not to fit the column. It is also well clear of the 64
    # characters NIST SP 800-63B asks verifiers to permit, so it rules out
    # nothing a person would plausibly choose.
    #
    # Measured against the *normalised* password (see `normalize_password` in
    # models.py), since that is the string actually hashed.
    PASSWORD_MAX_LENGTH = _positive_int_env("PASSWORD_MAX_LENGTH", 255)

    # -- Rate limiting ------------------------------------------------------
    # Keys below starting with RATELIMIT_ are read by Flask-Limiter itself.
    #
    # This matters because authorization is only as strong as the front door:
    # every role check in auth.py is bypassed by simply guessing an admin's
    # password, and without a limit that can be attempted as fast as the
    # network allows.
    # Pinned True, which is not the on/off switch it looks like. Flask-Limiter
    # reads this particular key itself while initialising and, when it is
    # false, skips setting up its storage backend — leaving a limiter that
    # cannot be switched on again afterwards. Since the test suite runs with
    # limits off and enables them for the tests that are about limits, storage
    # has to exist either way.
    #
    # The real state is `RATE_LIMITING_ACTIVE` below, which extensions.py
    # applies to `limiter.enabled` once the storage is up.
    RATELIMIT_ENABLED = True

    # The actual switch, still driven by a `RATELIMIT_ENABLED` environment
    # variable so there is only one name to remember from the outside.
    # Set `RATELIMIT_ENABLED=false` to turn limits off — necessary for load
    # testing, where hundreds of simulated users share one IP and would
    # otherwise all be throttled as a single abusive client.
    RATE_LIMITING_ACTIVE = (
        os.environ.get("RATELIMIT_ENABLED", "true").strip().lower() != "false"
    )

    # Where the counters live. The default keeps them in the worker's own
    # memory, which has two consequences worth knowing rather than
    # discovering: gunicorn runs several workers, each with its own counter,
    # so the effective limit is roughly the configured one times the worker
    # count; and a restart or redeploy resets every counter. That is a weaker
    # guarantee than it looks, but still turns unlimited guessing into a slow
    # trickle. Point this at a shared store to make the limits exact, e.g.
    #   RATELIMIT_STORAGE_URI=redis://default:password@host:6379
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://").strip()

    # Send X-RateLimit-* headers so a client can see its own budget instead of
    # having to infer it from a 429.
    RATELIMIT_HEADERS_ENABLED = True

    # Applies to every route without its own decorator. Generous: it is a
    # backstop against a runaway client, not the anti-brute-force measure.
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "300 per minute").strip()

    # Credential guessing. Deliberately the tightest limit in the app: a
    # person mistyping their password needs a handful of tries, while an
    # attacker needs millions.
    RATELIMIT_LOGIN = os.environ.get(
        "RATELIMIT_LOGIN", "10 per minute;100 per hour"
    ).strip()

    # Account creation, to stop a script filling the users table.
    RATELIMIT_REGISTER = os.environ.get(
        "RATELIMIT_REGISTER", "5 per minute;30 per hour"
    ).strip()

    # Token rotation. Looser, since a legitimate client refreshes roughly once
    # per access-token lifetime, but bounded because each call writes a
    # token_blocklist row.
    RATELIMIT_REFRESH = os.environ.get("RATELIMIT_REFRESH", "60 per minute").strip()

    # Number of proxies in front of the app whose X-Forwarded-For entries can
    # be trusted, used to recover the real client IP (see extensions.py).
    #
    # This has to be right or rate limiting misfires in one of two ways. Too
    # low on a deployed app and every request appears to come from the
    # platform's proxy, so one user's failed logins throttle everybody. Too
    # high and a client can prepend a forged X-Forwarded-For entry to get a
    # fresh quota per request, which defeats the limit entirely.
    #
    # Default 1 matches a single platform proxy such as Railway's. Set it to 0
    # when running with no proxy at all, so the header is ignored.
    TRUSTED_PROXY_COUNT = _non_negative_int_env("TRUSTED_PROXY_COUNT", 1)
