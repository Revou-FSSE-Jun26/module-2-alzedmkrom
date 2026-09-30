# RevoShop

A Flask + SQLAlchemy application layer built on top of the existing, already-populated `revoshop_db` PostgreSQL database from Checkpoint 1. It exposes database-backed endpoints for products, categories, orders, and user registration/retrieval, a Flask-Migrate history that adds a `role` column to `users` and an `is_delete` soft-delete column to both `products` and `orders`, and `flask` CLI commands for connection verification and many-to-many demonstration data.

Authentication is implemented with JSON Web Tokens: short-lived access tokens, rotating refresh tokens, database-backed revocation so logout takes effect immediately, and role-based authorization separating customers from admins. See [Authentication](#authentication). The API is deployed on Railway with its database hosted on Supabase (see Live Demo below), and also runs locally.

## Live Demo

The API is live on Railway, backed by a Supabase PostgreSQL database:

- **Base URL:** https://web-production-03650.up.railway.app
- **Health check:** [`GET /`](https://web-production-03650.up.railway.app/) → `{"message": "RevoShop API is running."}`
- **Example:** [`GET /products`](https://web-production-03650.up.railway.app/products) → JSON list of products

Example request:

```bash
curl https://web-production-03650.up.railway.app/products
```

## Overview

RevoShop is the backend for a small online store. It manages a catalog of **products** grouped into **categories**, lets **users** register and place **orders**, and records each order's line items in an `order_items` association table that links orders to products (many-to-many, with per-line `quantity` and `unit_price`). It is a Flask + SQLAlchemy REST API returning JSON, sitting on top of the PostgreSQL database (`revoshop_db`) designed in Checkpoint 1.

## Features Implemented

- **Full CRUD for products** — create, list, retrieve, update, and delete (`POST`/`GET`/`GET <id>`/`PUT`/`DELETE /products`).
- **Full CRUD for categories** — create, list, retrieve (with the category's products), update, and delete (`/categories`).
- **Full CRUD for orders** — place an order, list a user's orders, retrieve one order with its line items and product details, update status, and delete (`/orders`).
- **User registration and retrieval** — `POST /users`, `GET /users/<id>`. Passwords are hashed with Werkzeug and never returned.
- **JWT authentication** — `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`. Short-lived access tokens with longer-lived refresh tokens, and every failure carrying a machine-readable `code` so a client can tell "refresh and retry" from "log out". See [Authentication](#authentication).
- **Refresh-token rotation with an idle session timeout** — each refresh revokes the token it consumed and issues a new pair, so an active session slides forward while an idle one expires and forces a fresh login (the auto-logout).
- **Immediate logout via database-backed revocation** — revoked tokens are recorded in `token_blocklist` and refused for the rest of their lifetime, rather than staying valid until they expire. Stored in the database, not in memory, so revocation holds across gunicorn workers and redeploys.
- **Role-based authorization** — catalog reads are public, orders are scoped to the authenticated user, and product/category writes plus order status changes are admin-only. Roles are re-read from the database per request, so a demotion or deactivation takes effect immediately instead of when the token expires. `POST /users` refuses to honor a self-assigned `role`.
- **CORS** — an explicit, environment-configured origin allowlist, so a browser frontend on another origin can call the API.
- **Password policy** — registration requires 8 to 255 characters including a letter and a digit. Case is not mandated but is preserved, so passwords stay case-sensitive. Enforced at sign-up only, so older accounts are not locked out.
- **Unicode-safe passwords** — passwords are NFKC-normalised before hashing and verifying, so a password containing non-ASCII characters keeps working whichever keyboard or OS types it, instead of failing on an encoding difference the user cannot see.
- **Rate limiting** — per-IP caps, tightest on `POST /auth/login`, which is what makes password guessing impractical. Exceeding one returns a JSON `429` with `Retry-After`, and `X-RateLimit-*` headers report the remaining budget.
- **Many-to-many between orders and products through `order_items`** — each order line stores its own `quantity` and the `unit_price` captured at order time, so an order is a faithful record of what was actually charged. `flask link-order-products` demonstrates one order linked to multiple products.
- **Data validation** — every write endpoint validates required fields, types, ranges, and lengths, returning `400`/`422` with a clear message on bad input, and `409` on conflicts (duplicate category/user, delete blocked by references).
- **Error handling with `try`/`except`** — all database writes are wrapped so an `IntegrityError` maps to `409` and any other `SQLAlchemyError` rolls back and maps to `500`, with the internal detail logged (never leaked). Framework 404/405 responses are also returned as JSON.
- **Deletion guard on products** — `DELETE /products/<id>` will not remove a product that still has **active** orders (any non-finalized status): it returns `409`. A product whose orders are all finalized is soft-deleted (`is_delete = true`) to preserve order history, and a product never ordered is hard-deleted.
- **Stock management** — placing an order decrements product stock (and rejects an order that exceeds available stock); cancelling/returning/refunding an order restores it.
- **Soft delete for orders** — `DELETE /orders/<id>` sets `is_delete = true` instead of removing the row, so financial/order history is never destroyed.
- **Automated tests** — a `pytest` suite (`tests/`) covers all Category CRUD endpoints plus users, products, and orders, on happy-path and error cases, against an isolated test database.
- **Load testing** — a `locustfile.py` simulates a concurrent shopper journey (log in → browse → view → order → view order → refresh token), run against a throwaway database.

## Technologies Used

- **Flask** — web framework and routing (via blueprints).
- **SQLAlchemy** — ORM and query layer.
- **Flask-Migrate** (Alembic) — version-controlled schema migrations.
- **Flask-JWT-Extended** — access/refresh token issuing, verification, and the revocation hook.
- **Flask-Cors** — cross-origin access for the browser frontend.
- **Flask-Limiter** — per-IP request limits on the authentication endpoints.
- **PostgreSQL** — the relational database (`revoshop_db`).
- **pgAdmin** — GUI for inspecting the local database and tables.
- **pytest** — the automated test suite.
- **Locust** — load/performance testing.
- **python-dotenv** — loads configuration and secrets from `.env`.
- **Werkzeug** — password hashing (ships with Flask).
- **psycopg2** — PostgreSQL driver.

## Project Files

- `schema.sql`, `seed.sql`, `queries.sql` — Checkpoint 1 database design, sample data, and verification queries. Unchanged by this checkpoint.
- `config.py` — the `Config` class (database URIs, `SECRET_KEY`, CORS origins, JWT lifetimes, admin role name, password policy, rate limits).
- `extensions.py` — the module-level `app`, `db = SQLAlchemy(app)`, `migrate = Migrate(app, db)`, `cors`, `jwt = JWTManager(app)`, and `limiter` (plus the `ProxyFix` that recovers the real client IP behind a platform proxy).
- `models.py` — `User`, `Category`, `Product`, `Order`, `TokenBlocklist`, the `order_items` association table, and `normalize_password` (the NFKC normalisation both `set_password` and `check_password` apply).
- `routes.py` — `home_bp`, `products_bp`, `categories_bp`, `orders_bp`, and `users_bp` (which also carries the `/auth/*` endpoints), all database-backed.
- `errors.py` — JSON error handlers for 400/404/405/429/500.
- `auth.py` — the JWT callbacks (identity, user lookup, revocation check, JSON failure responses) and the `admin_required` / owner-or-admin guards used by `routes.py`.
- `cli.py` — `flask check-db` and `flask link-order-products`.
- `locustfile.py` — Locust load test simulating a shopper journey (list products, view one, place an order, view that order).
- `app.py` — entry point; registers blueprints and runs the dev server.
- `migrations/` — the Flask-Migrate environment and revision history.
- `requirements.txt` — runtime dependencies, pinned. This is what the deployment host installs.
- `requirements-dev.txt` — `pytest` and `locust`, kept separate so they are not installed into the deployed image.
- `Procfile` — the process command the host runs: `gunicorn app:app --bind 0.0.0.0:$PORT`.

## Setup

### 1. Create and activate a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux (POSIX shells):

```sh
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

Dependencies are split across two files, because the deployment host installs the runtime one on every build and neither the test runner nor the load-test tool is needed to serve a request:

- **`requirements.txt`** — what the app needs to run: Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-JWT-Extended, Flask-Cors, SQLAlchemy, alembic, `psycopg2-binary`, `python-dotenv`, and `gunicorn`, plus their pinned transitive dependencies.
- **`requirements-dev.txt`** — `pytest` and `locust`, for the test suite and load testing.

To work on the project, install both:

```sh
pip install -r requirements.txt -r requirements-dev.txt
```

To run it (or deploy it), the runtime file alone is enough:

```sh
pip install -r requirements.txt
```

### 3. Configure the connection

There are two environment files:

- **`.flaskenv`** (committed, holds no secrets) — sets `FLASK_APP=app.py` and `FLASK_DEBUG=1`, which is what lets `flask run`, `flask db ...`, and the custom `flask` commands find the app with no extra flags.
- **`.env`** (gitignored, must never be committed) — copy `.env.example` to `.env` and fill in real values:

  ```sh
  cp .env.example .env
  ```

  `config.py` calls `load_dotenv()` on import, so every value below comes from `.env` (or the real shell/host environment in production, which `python-dotenv` never overrides). `DATABASE_URL` and `SECRET_KEY` have no hardcoded fallback: a missing `.env` fails loudly at startup with a `KeyError` instead of silently connecting to the wrong database. Everything else is optional and documented with its default in `.env.example`.

  **Required:**

  - **`DATABASE_URL`** — PostgreSQL connection string, in `postgresql://user:password@host/dbname` form. Any PostgreSQL will do: a local instance, or a hosted one such as Supabase (this project's own deployment uses Supabase — see `.env.example` for the pooler details that setup needs).
  - **`SECRET_KEY`** — used by Flask for session signing, and as the fallback signing key for JWTs. Generate a value with:

    ```sh
    python -c "import secrets; print(secrets.token_hex(32))"
    ```

  **Optional, with sensible defaults:**

  - **`FLASK_DEBUG`** — `true` to enable Flask's debug mode (auto-reload, interactive debugger) when running via `python app.py`. **Must be `false` on a deployed host**: Flask ties `PROPAGATE_EXCEPTIONS` to `DEBUG`, so with debug on an unhandled error bypasses the JSON handlers in `errors.py` and the client gets the WSGI server's HTML error page, which a frontend calling `response.json()` cannot parse. (`flask run` reads its own `FLASK_DEBUG` from `.flaskenv` instead, independently of this one.)
  - **`DIRECT_URL`** — a separate connection string used only by migrations, needed when `DATABASE_URL` points at a connection pooler that cannot run DDL transactions. Falls back to `DATABASE_URL`.
  - **`CORS_ORIGINS`** — origins allowed to call the API from a browser. Defaults to the usual local frontend dev servers.
  - **`JWT_SECRET_KEY`**, **`JWT_ACCESS_MINUTES`**, **`JWT_REFRESH_MINUTES`**, **`ADMIN_ROLE`** — see [Authentication](#authentication).
  - **`PASSWORD_MIN_LENGTH`**, **`RATELIMIT_*`**, **`TRUSTED_PROXY_COUNT`** — see [Password policy](#password-policy) and [Rate limiting](#rate-limiting).

### 4. Confirm the database is reachable

```sh
flask check-db
```

See [CLI Commands](#cli-commands) below for expected output.

## Running the App

Either launch path works, since `app.py` never runs `app.run()` except inside its own `__main__` block, and `flask run` discovers the module-level `app` directly.

**Option A — `python app.py`**

```sh
python app.py
```

Runs the built-in Werkzeug server with `debug=True` set directly in the `app.run()` call. Serves on `http://127.0.0.1:5000` by default.

**Option B — `flask run`**

```sh
flask run
```

Uses `FLASK_APP=app.py` from `.flaskenv` to find the app, and `FLASK_DEBUG=1` from the same file to enable the debugger/reloader (this path never executes the `__main__` block, so debug mode has to come from `.flaskenv` instead of the `app.run()` call). Also serves on `http://127.0.0.1:5000` by default.

## Migrations

The migration history is baselined on top of the already-populated `revoshop_db` rather than recreating it. The `migrations/versions/` directory contains six revisions, applied in this order:

| Order | Revision ID | File | Description |
|---|---|---|---|
| 1 | `b0725bc519d7` | `b0725bc519d7_baseline_checkpoint_1_schema.py` | Baseline: describes the five Checkpoint 1 tables, the two case-insensitive unique indexes, and the three foreign-key indexes exactly as they already exist. **Stamped, not upgraded**, against the populated database. |
| 2 | `44a808644adc` | `44a808644adc_add_unique_constraints_to_users_.py` | Adds plain unique constraints (`users_username_key`, `users_email_key`) on `users.username`/`users.email`, on top of the existing case-insensitive functional indexes. |
| 3 | `67d9a832861f` | `67d9a832861f_add_role_to_users.py` | Adds `users.role` (`VARCHAR(50) NOT NULL`) with a server default of `'CUSTOMER'`, backfilling all existing rows in the same statement. |
| 4 | `48a1dad68d30` | `48a1dad68d30_add_is_active_to_products.py` | Adds `products.is_active` (`BOOLEAN NOT NULL`) with a server default of `true`, backfilling all existing rows in the same statement. Superseded by revision 5 below. |
| 5 | `e4e6cb9cdcda` | `e4e6cb9cdcda_add_order_is_delete_rename_product_is_.py` | Adds `orders.is_delete` (`BOOLEAN NOT NULL`, default `false`). Renames `products.is_active` to `products.is_delete`, inverting both the column's polarity and its data (`is_delete = NOT is_active`) so both tables use the same `is_delete` naming/meaning. |
| 6 | `56e0d1e07c3f` | `56e0d1e07c3f_add_token_blocklist_for_jwt_revocation.py` | Adds the `token_blocklist` table (`jti` unique, `token_type`, `user_id` FK with `ON DELETE CASCADE`, `expires_at`, `revoked_at`) plus indexes on `jti` and `expires_at`. Backs JWT revocation, so logout takes effect immediately instead of when the token expires. This is the current head. |

### Commands used

Initialize the migration environment (already done in this repository; included for reference):

```sh
flask db init
```

Generate a new revision after changing a model in `models.py`:

```sh
flask db migrate -m "description of the change"
```

**Review the generated file** in `migrations/versions/` before applying it. Autogenerate on this project's revisions needed hand correction each time (unnamed constraints from `batch_alter_table`, PostgreSQL not needing SQLite-style table recreation, and `compare_server_default` being off by default), so never apply a generated revision without reading it first.

Apply pending revisions:

```sh
flask db upgrade
```

### Baseline path for an existing populated database

Because `revoshop_db` already contains the five tables with 10 users, 4 categories, 10 products, 30 orders, and 56 order items, running the baseline revision's `upgrade()` would try to `CREATE TABLE` tables that already exist and fail. Instead, the baseline is recorded as already applied, without executing any DDL:

```sh
flask db stamp b0725bc519d7
```

Then apply the remaining revisions normally:

```sh
flask db upgrade
```

This brings `revoshop_db` to `e4e6cb9cdcda` (the current head) while preserving every existing row.

### Upgrade-from-empty path for a fresh database

A reviewer starting from an empty database does not stamp anything. Create an empty `revoshop_db` (or equivalent) and run every revision from the beginning:

```sh
flask db upgrade
```

This builds the same schema from scratch, so the migration history is genuinely replayable in either direction: stamp+upgrade for the populated database this project actually targets, or upgrade-from-empty for a clean one.

### Verifying a migration

After any `flask db upgrade`, run:

```sh
flask check-db
```

and confirm the row counts read 10 / 4 / 10 / 30 / 56 (a fresh Checkpoint 1 seed inserts 54 order_items; the two extra come from `flask link-order-products`, which extends order 4 for the many-to-many demonstration). The `users` count may read higher than 10 if `POST /users` has been exercised since seeding, and `orders`/`order_items` may read higher after local API or Locust testing; that is expected and does not indicate data loss, since the original seeded rows are still present. Re-running `queries.sql` in a database client should still return no rows from its integrity checks.

## Authentication

Access tokens are sent in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Who can reach what

| Access | Endpoints |
| --- | --- |
| **Public** (no token) | `GET /`, `POST /users`, `POST /auth/login`, `GET /products`, `GET /products/<id>`, `GET /categories`, `GET /categories/<id>` |
| **Any logged-in user** | `GET /auth/me`, `POST /auth/refresh`, `POST /auth/logout`, `GET /users/<id>` (self), `POST /orders`, `GET /orders`, `GET /orders/<id>` (own), `DELETE /orders/<id>` (own) |
| **Admin only** (`role = 'ADMIN'`) | `POST`/`PUT`/`DELETE /products`, `POST`/`PUT`/`DELETE /categories`, `PUT /orders/<id>`, plus any other user's orders and `GET /users/<id>` for any id |

Two distinct refusals, and they mean different things:

- **401** — not authenticated (no token, expired, revoked, malformed). Authenticate and retry.
- **403** — authenticated fine, but not allowed. Retrying with the same account will not help.

### The four auth endpoints

**`POST /auth/login`** — exchange credentials for a token pair.

```json
// request
{ "email": "alice@example.com", "password": "hunter2" }

// 200
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 604800,
  "user": { "id": 1, "username": "alice", "role": "CUSTOMER", ... }
}
```

`expires_in` and `refresh_expires_in` are seconds, so a client can refresh shortly before the access token lapses instead of waiting to be surprised by a 401. A wrong password and an unknown email return the identical 401 (`"code": "invalid_credentials"`), so the endpoint cannot be used to discover which accounts exist. A deactivated account gets `"code": "account_inactive"`.

**`POST /auth/refresh`** — send the **refresh** token in the header, receive a new pair.

The refresh token presented is revoked as part of the exchange (rotation), so each one is single-use. Store both halves of the response; keeping the old refresh token guarantees a `token_revoked` failure next time.

**`POST /auth/logout`** — send the **access** token in the header, and the refresh token in the body:

```json
{ "refresh_token": "eyJ..." }
```

Both are then rejected for the rest of their natural lifetime. Sending the refresh token is optional but strongly recommended: omit it and a working refresh token survives, so the session is not really over. A malformed value there is ignored rather than rejected — the point of logout is that the caller ends up logged out.

**`GET /auth/me`** — the account behind the access token. Useful for restoring a session on page reload, and the cheapest way to ask "is my token still good?".

### Session timeout and auto-logout

Two timers, with different meanings:

| Token | Default | Expiry means |
| --- | --- | --- |
| Access | 15 min (`JWT_ACCESS_MINUTES`) | Recoverable. Refresh and retry; the user notices nothing. |
| Refresh | 7 days (`JWT_REFRESH_MINUTES`) | The session is over. Clear both tokens and show the login screen. |

Because every refresh rotates the token, the refresh lifetime behaves as an **idle** timeout: an active client keeps trading its way forward indefinitely, while a client that goes quiet for longer than that window cannot renew and has to log in again. That is the auto-logout. Set `JWT_REFRESH_MINUTES` low (say `2`) to watch it happen.

Errors carry a machine-readable `code`, and an expiry also echoes which token expired, so a frontend can branch without parsing prose:

```json
// 401 — access token aged out: refresh and retry
{ "error": "Unauthorized", "message": "Access token expired. ...",
  "code": "token_expired", "token_type": "access" }

// 401 — from POST /auth/refresh: the session is over, log out
{ "error": "Unauthorized", "message": "Session expired. Please log in again.",
  "code": "token_expired", "token_type": "refresh" }
```

Full set of codes: `authorization_required`, `token_expired`, `token_revoked`, `token_invalid`, `user_unavailable`, `admin_required`, `forbidden`, `invalid_credentials`, `account_inactive`, `fresh_token_required`, `weak_password`, `rate_limit_exceeded`.

### Suggested frontend flow

1. Log in, keep both tokens.
2. Send the access token on every authenticated request.
3. On a 401 with `code = "token_expired"` and `token_type = "access"`: call `/auth/refresh`, replace **both** tokens, replay the original request once.
4. On any other 401 (including a `token_expired` refresh, or `token_revoked`): discard both tokens and redirect to login.
5. On logout, call `/auth/logout` with the refresh token in the body before clearing local state.

### Password policy

`POST /users` requires a password that is:

- between **8** and **255 characters** (`PASSWORD_MIN_LENGTH` / `PASSWORD_MAX_LENGTH`)
- containing at least **one letter**
- containing at least **one digit**

No uppercase character is required. Passwords are nonetheless **fully case-sensitive**: nothing is lowercased anywhere, and normalisation does not fold case, so `secret1` and `Secret1` are different passwords.

A rejection names the single rule that failed, with `"code": "weak_password"`:

```json
{ "error": "Bad Request",
  "message": "Password must be at least 8 characters long.",
  "code": "weak_password" }
```

Whitespace is not stripped before counting, since a space is a legitimate password character. Whitespace-only passwords still fail, on the letter and digit rules.

The maximum is a tidiness bound, not a constraint from the `password_hash` column: that column stores the hash, which PBKDF2 emits at a fixed ~162 characters however long the password was. 255 is well clear of the 64 characters [NIST SP 800-63B asks verifiers to permit](https://github.com/usnistgov/800-63-3/blob/nist-pages/sp800-63b/sec5_authenticators.md).

**Unicode passwords are normalised (NFKC) before hashing and before verifying.** Non-ASCII characters are accepted, and normalising is what makes them reliable rather than a trap. The same visible character frequently has more than one valid encoding — `é` is either one code point or two, `e` plus a combining accent — which are different strings underneath while being indistinguishable on screen. Hash one spelling and compare the other and verification fails, so without normalising, whether login works depends on the keyboard, operating system, or paste buffer the password arrived through, and nothing in the response could explain the failure.

Two consequences worth knowing:

- Length is measured **after** normalising, since that is the string that gets hashed. `café1234` typed as `e`+accent is 9 characters raw and 8 normalised, and the 8 is what counts.
- NFKC also applies compatibility folding, which is mildly lossy: `²` becomes `2`, full-width `ｐ` becomes `p`. So `password²` satisfies the digit rule as a genuine `2`, and two passwords that look different can normalise to the same one. That is the intended trade — a slightly smaller password space for a password that keeps working wherever it is typed.

**Login never re-checks the policy.** Accounts created before it existed have working passwords that would not satisfy it, and re-checking at sign-in would lock them out of their own accounts rather than prompting anyone to pick something better.

**Login never re-checks the policy.** Accounts created before it existed have working passwords that would not satisfy it, and re-checking at sign-in would lock them out of their own accounts rather than prompting anyone to pick something better.

### Rate limiting

Requests are capped per client IP. This is the companion to the password policy rather than a capacity control: every role check above is bypassed by guessing an admin's password, and guessing is only expensive when attempts are capped.

| Endpoint | Default limit | Why |
| --- | --- | --- |
| `POST /auth/login` | 10/min, 100/hour | Tightest in the app: no credentials needed to start guessing. |
| `POST /users` | 5/min, 30/hour | Stops a script filling the users table. |
| `POST /auth/refresh` | 60/min | A real client refreshes rarely, and each call writes a `token_blocklist` row. |
| everything else | 300/min | Backstop against a runaway client; browsing stays comfortable. |

Exceeding a limit returns `429` in the usual envelope, with `Retry-After` and the limit that tripped. Every response also carries `X-RateLimit-*` headers, so a client can watch its own budget instead of inferring it from a rejection.

```json
{ "error": "Too Many Requests",
  "message": "Too many requests. Please slow down and try again shortly.",
  "code": "rate_limit_exceeded",
  "limit": "10 per 1 minute" }
```

Two behaviours worth knowing:

- **Failed attempts count**, and once the limit trips even the *correct* password is refused until the window passes. Otherwise an attacker's final successful guess would still be rewarded.
- `429` and `401` are distinguishable by `code`, so a frontend can say "too many attempts, wait a moment" rather than "wrong password" for something that is not a password problem.

**Honest limitations of the default setup.** Counters live in each worker's memory (`RATELIMIT_STORAGE_URI=memory://`), which means gunicorn's several workers each keep their own, so the effective limit is roughly the configured one times the worker count; and a restart or redeploy clears them. That is weaker than it looks, though it still turns unlimited guessing into a trickle. Point `RATELIMIT_STORAGE_URI` at Redis to make the limits exact.

`TRUSTED_PROXY_COUNT` must match the deployment or limiting misfires: too low and every request appears to come from the platform proxy, so one user's failed logins throttle everybody; too high and a client can forge an `X-Forwarded-For` entry for a fresh quota per request. `1` is correct behind Railway; use `0` with no proxy.

**Load testing requires `RATELIMIT_ENABLED=false`** on the server, since all of Locust's simulated users share one IP and would otherwise be throttled as a single abusive client.

### Roles

`users.role` defaults to `'CUSTOMER'`. `POST /users` **ignores** a caller-supplied `role` unless the request already carries an admin token — otherwise anyone could mint themselves an admin account with one unauthenticated request. The first admin therefore has to be promoted directly in the database:

```sql
UPDATE users SET role = 'ADMIN' WHERE email = 'you@example.com';
```

Role is re-read from the database on every request rather than trusted from the token claim, so promoting, demoting, or deactivating an account takes effect on that account's next request instead of whenever its current token happens to expire.

### Notes

- Tokens are read from the `Authorization` header only. Cookies are deliberately not enabled: the API is called cross-origin by a browser frontend, and cookie-based JWT would need CSRF protection as well.
- Revocations live in the `token_blocklist` table, not in memory, because gunicorn runs multiple workers (a token revoked in one would still be accepted by the others) and a redeploy would otherwise silently un-revoke everything.
- Accounts created by `seed.sql` **cannot log in**: it stores placeholder strings such as `hash_budi_001` in `password_hash` rather than real Werkzeug hashes. Register through `POST /users` to get a usable account.

## Endpoints

Authorization per endpoint is summarized in [Authentication](#who-can-reach-what) above; the descriptions below cover request/response shapes and validation.

All error responses (including framework-generated 404s and 405s) are returned as JSON:

```json
{ "error": "Not Found", "message": "..." }
```

### GET /

Confirms the app is running.

Request:

```sh
curl http://127.0.0.1:5000/
```

Response — `200 OK`:

```json
{
  "message": "RevoShop API is running."
}
```

### POST /products

Creates a product. Requires `category_id` (integer referencing an existing category), `name` (non-blank, <= 255 chars), `price` (finite number >= 0), and `stock_quantity` (integer >= 0). `description` is optional. Returns `201 Created` with `Product.to_dict()`.

Request (success):

```sh
curl -X POST http://127.0.0.1:5000/products \
  -H "Content-Type: application/json" \
  -d '{"category_id": 1, "name": "Denim Jacket", "description": "Classic fit", "price": 250000, "stock_quantity": 40}'
```

Response — `201 Created`:

```json
{
  "id": 11,
  "category_id": 1,
  "name": "Denim Jacket",
  "description": "Classic fit",
  "price": 250000.0,
  "stock_quantity": 40,
  "is_delete": false,
  "created_at": "2026-08-28T12:00:00+07:00"
}
```

Request (missing required field):

```sh
curl -X POST http://127.0.0.1:5000/products \
  -H "Content-Type: application/json" \
  -d '{"category_id": 1, "name": "Denim Jacket"}'
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "Missing or blank field(s): price, stock_quantity"
}
```

Request (unknown category):

```sh
curl -X POST http://127.0.0.1:5000/products \
  -H "Content-Type: application/json" \
  -d '{"category_id": 999, "name": "Denim Jacket", "price": 250000, "stock_quantity": 40}'
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "category_id 999 does not reference an existing category."
}
```

### GET /products

Returns products, ordered by `id`, via `Product.to_dict()`. Soft-deleted
products (`is_delete: true`) are excluded by default, matching a real
storefront. Pass `?include_deleted=true` to also list them.

Request:

```sh
curl http://127.0.0.1:5000/products
```

Response — `200 OK`:

```json
[
  {
    "id": 1,
    "category_id": 2,
    "name": "Nike Air Max Running Shoes",
    "description": "Lightweight and comfortable for jogging",
    "price": 850000.0,
    "stock_quantity": 50,
    "is_delete": false,
    "created_at": "2026-08-14T18:44:04.027788+07:00"
  },
  {
    "id": 2,
    "category_id": 1,
    "name": "Plain Cotton Combed T-Shirt",
    "description": "Breathable material, available in various colors",
    "price": 75000.0,
    "stock_quantity": 200,
    "is_delete": false,
    "created_at": "2026-08-14T18:44:04.027788+07:00"
  }
  // ... remaining products
]
```

Request (include soft-deleted products too):

```sh
curl "http://127.0.0.1:5000/products?include_deleted=true"
```

### GET /products/\<id\>

Returns the product matching `id` via `Product.to_dict()`, or a 404 JSON
error naming the id. Returned regardless of `is_delete`, so a soft-deleted
product referenced by a past order still resolves by id.

Request (found):

```sh
curl http://127.0.0.1:5000/products/1
```

Response — `200 OK`:

```json
{
  "id": 1,
  "category_id": 2,
  "name": "Nike Air Max Running Shoes",
  "description": "Lightweight and comfortable for jogging",
  "price": 850000.0,
  "stock_quantity": 50,
  "is_delete": false,
  "created_at": "2026-08-14T18:44:04.027788+07:00"
}
```

Request (not found):

```sh
curl http://127.0.0.1:5000/products/999
```

Response — `404 Not Found`:

```json
{
  "error": "Not Found",
  "message": "Product 999 was not found."
}
```

### PUT /products/\<id\>

Partially updates a product. Only the keys present in the body are changed (`name`, `description`, `price`, `stock_quantity`, `category_id`); omitted keys are left as-is. A `category_id`, if present, must reference an existing category. Returns `200 OK` with the updated `Product.to_dict()`.

Request (success):

```sh
curl -X PUT http://127.0.0.1:5000/products/1 \
  -H "Content-Type: application/json" \
  -d '{"price": 799000, "stock_quantity": 45}'
```

Response — `200 OK`:

```json
{
  "id": 1,
  "category_id": 2,
  "name": "Nike Air Max Running Shoes",
  "description": "Lightweight and comfortable for jogging",
  "price": 799000.0,
  "stock_quantity": 45,
  "is_delete": false,
  "created_at": "2026-08-14T18:44:04.027788+07:00"
}
```

Request (invalid value — negative price):

```sh
curl -X PUT http://127.0.0.1:5000/products/1 \
  -H "Content-Type: application/json" \
  -d '{"price": -5}'
```

Response — `422 Unprocessable Entity`:

```json
{
  "error": "Bad Request",
  "message": "price must be 0 or greater"
}
```

Request (not found):

```sh
curl -X PUT http://127.0.0.1:5000/products/999 \
  -H "Content-Type: application/json" \
  -d '{"price": 100}'
```

Response — `404 Not Found`:

```json
{
  "error": "Not Found",
  "message": "Product 999 was not found."
}
```

### DELETE /products/\<id\>

Removes a product, but only actually deletes the row if it is safe to do
so. `order_items.product_id` has `ON DELETE RESTRICT` at the database
level, so a real deletion is only possible when nothing references the
product; the route decides between three outcomes based on the status of
every order that has ever included this product:

| Order history | Outcome | Status |
|---|---|---|
| At least one order is not finalized (`PENDING`, `PROCESSING`, `SHIPPED`, or any other non-finalized status) | Blocked; nothing changes | `409 Conflict` |
| No orders ever referenced the product | Hard delete; the row is removed | `200 OK` |
| Every referencing order is finalized (`COMPLETED`, `CANCELLED`, `RETURNED`, `REFUNDED`) | Soft delete; `is_delete` is set to `true` | `200 OK` |

A soft-deleted product disappears from the default `GET /products` list and
can no longer be ordered again, while every past order that references it
keeps resolving correctly (see `GET /orders/<id>`).

Request (blocked by an active order):

```sh
curl -X DELETE http://127.0.0.1:5000/products/2
```

Response — `409 Conflict`:

```json
{
  "error": "Conflict",
  "message": "Product 2 cannot be deleted because it has one or more active orders (status: PENDING, PROCESSING)."
}
```

Request (never ordered — hard delete):

```sh
curl -X DELETE http://127.0.0.1:5000/products/14
```

Response — `200 OK`:

```json
{
  "message": "Product 14 deleted successfully."
}
```

Request (only finalized orders — soft delete):

```sh
curl -X DELETE http://127.0.0.1:5000/products/15
```

Response — `200 OK`:

```json
{
  "message": "Product 15 has only finalized orders and has been soft-deleted instead of removed, preserving order history."
}
```

Request (not found):

```sh
curl -X DELETE http://127.0.0.1:5000/products/999
```

Response — `404 Not Found`:

```json
{
  "error": "Not Found",
  "message": "Product 999 was not found."
}
```

### POST /categories

Creates a category. Requires a non-blank `name` (<= 255 chars) that is not already taken; `description` is optional. Returns `201 Created` with `Category.to_dict()`.

```sh
curl -X POST http://127.0.0.1:5000/categories \
  -H "Content-Type: application/json" \
  -d '{"name": "Electronics", "description": "Gadgets and devices"}'
```

Response — `201 Created`:

```json
{ "id": 5, "name": "Electronics", "description": "Gadgets and devices" }
```

Duplicate name returns `409 Conflict` (`{"error": "Conflict", "message": "Category name already exists."}`); a missing/blank name returns `400 Bad Request`.

### GET /categories

Returns all categories, ordered by `id`.

```sh
curl http://127.0.0.1:5000/categories
```

Response — `200 OK`:

```json
[
  { "id": 1, "name": "Apparel", "description": "Collection of t-shirts, pants, jackets, and other garments" },
  { "id": 2, "name": "Footwear", "description": "Athletic shoes, casual shoes, and socks" }
]
```

### GET /categories/\<id\>

Returns the category plus its products (a `products` array of `Product.to_dict()`), or `404` naming the id.

```sh
curl http://127.0.0.1:5000/categories/1
```

Response — `200 OK`:

```json
{
  "id": 1,
  "name": "Apparel",
  "description": "Collection of t-shirts, pants, jackets, and other garments",
  "products": [
    { "id": 2, "category_id": 1, "name": "Plain Cotton Combed T-Shirt", "description": "Breathable material, available in various colors", "price": 75000.0, "stock_quantity": 200, "is_delete": false, "created_at": "2026-08-14T18:44:04.027788+07:00" }
  ]
}
```

### PUT /categories/\<id\>

Partially updates a category's `name` and/or `description` (only keys present are changed). A new `name` must be non-blank, <= 255 chars, and not collide with another category. Returns `200 OK` with `Category.to_dict()`, `404` if not found, or `409` on a name collision.

```sh
curl -X PUT http://127.0.0.1:5000/categories/5 \
  -H "Content-Type: application/json" \
  -d '{"description": "Phones, laptops, and accessories"}'
```

Response — `200 OK`:

```json
{ "id": 5, "name": "Electronics", "description": "Phones, laptops, and accessories" }
```

### DELETE /categories/\<id\>

Deletes a category. `products.category_id` has `ON DELETE RESTRICT`, so a category that still has products cannot be deleted.

```sh
curl -X DELETE http://127.0.0.1:5000/categories/5
```

Response — `200 OK`:

```json
{ "message": "Category 5 deleted successfully." }
```

Response — `409 Conflict` (still has products):

```json
{
  "error": "Conflict",
  "message": "Category cannot be deleted because it still has associated products."
}
```

### POST /orders

Places an order **for the authenticated user**. Requires an access token; the owner comes from that token, so there is no `user_id` in the body (one sent anyway is ignored, and cannot redirect the order to another account). There is no "order on behalf of" path, not even for admins.

Requires a non-empty `items` array, each item an object with `product_id` (existing product) and `quantity` (integer > 0, not exceeding the product's current stock). The same `product_id` cannot appear twice. The server sets `status` to `PENDING` and computes `total_price` itself; `unit_price` is captured from each product's current price, and each product's `stock_quantity` is decremented. If any item fails validation the whole order is rejected (all-or-nothing).

```sh
curl -X POST http://127.0.0.1:5000/orders \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d '{"items": [{"product_id": 3, "quantity": 2}, {"product_id": 6, "quantity": 1}]}'
```

Response — `201 Created`:

```json
{
  "id": 31,
  "user_id": 1,
  "total_price": 445000.0,
  "status": "PENDING",
  "is_delete": false,
  "created_at": "2026-08-28T12:00:00+07:00"
}
```

Request (insufficient stock):

```sh
curl -X POST http://127.0.0.1:5000/orders \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d '{"items": [{"product_id": 5, "quantity": 9999}]}'
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "items[0].product_id 5 has only 30 in stock, which is less than the requested quantity (9999)."
}
```

### GET /orders

Returns the **authenticated user's** orders, ordered by `id`. Requires an access token. `user_id` used to be a required query parameter; it is now taken from the token, so a customer cannot read someone else's history by changing a number.

An admin may pass `?user_id=<id>` to read a specific customer's orders. Any other caller passing it gets 403 rather than a silent fallback to their own orders. Soft-deleted orders are excluded by default; pass `?include_deleted=true` to include them.

```sh
curl "http://127.0.0.1:5000/orders" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response — `200 OK`:

```json
[
  { "id": 1, "user_id": 1, "total_price": 905000.0, "status": "COMPLETED", "is_delete": false, "created_at": "2026-08-14T18:44:13.652192+07:00" }
]
```

A missing/non-numeric `user_id` returns `400`; an unknown `user_id` returns `404`.

### GET /orders/\<id\>

Returns a single order with its line items and full product details, or `404` naming the id. Each item carries `quantity`, `unit_price` (the price captured at order time), and the nested `product`. Returned regardless of `is_delete`.

```sh
curl http://127.0.0.1:5000/orders/1
```

Response — `200 OK`:

```json
{
  "id": 1,
  "user_id": 1,
  "total_price": 905000.0,
  "status": "COMPLETED",
  "is_delete": false,
  "created_at": "2026-08-14T18:44:13.652192+07:00",
  "items": [
    { "quantity": 1, "unit_price": 850000.0, "product": { "id": 1, "category_id": 2, "name": "Nike Air Max Running Shoes", "description": "Lightweight and comfortable for jogging", "price": 850000.0, "stock_quantity": 50, "is_delete": false, "created_at": "2026-08-14T18:44:04.027788+07:00" } }
  ]
}
```

### PUT /orders/\<id\>

Updates an order's `status` — the only field a client may change (line items and totals are a permanent record of what was charged). `status` must be a non-blank string of 75 characters or fewer; it is normalized to uppercase. Once an order reaches a finalized status (`COMPLETED`, `CANCELLED`, `RETURNED`, `REFUNDED`) it is locked and further updates return `409`. Moving to `CANCELLED`, `RETURNED`, or `REFUNDED` restores each item's quantity back to product stock; `COMPLETED` does not.

```sh
curl -X PUT http://127.0.0.1:5000/orders/2 \
  -H "Content-Type: application/json" \
  -d '{"status": "SHIPPED"}'
```

Response — `200 OK`:

```json
{ "id": 2, "user_id": 2, "total_price": 195000.0, "status": "SHIPPED", "is_delete": false, "created_at": "2026-08-14T18:44:13.652192+07:00" }
```

Response — `409 Conflict` (order already finalized):

```json
{
  "error": "Conflict",
  "message": "Order 2 is COMPLETED and can no longer be updated."
}
```

### DELETE /orders/\<id\>

Soft-deletes an order: sets `is_delete = true` rather than removing the row, so order history and totals are never lost. Works for an order in any status. A soft-deleted order is hidden from `GET /orders` by default but still resolves via `GET /orders/<id>`.

```sh
curl -X DELETE http://127.0.0.1:5000/orders/31
```

Response — `200 OK`:

```json
{ "message": "Order 31 deleted successfully." }
```

### POST /users

Creates a new user account. Public: no token required. Validates the body, checks for a case-insensitive duplicate on `username`/`email`, hashes the password with Werkzeug, and persists the row.

The password must satisfy the [password policy](#password-policy): at least 8 characters, with a letter and a digit.

An optional `role` is **ignored unless the request carries an admin token** — see [Roles](#roles). An ordinary sign-up always produces a `CUSTOMER`, even if it sends something else.

Rate limited to 5 per minute and 30 per hour per IP.

Request (success):

```sh
curl -X POST http://127.0.0.1:5000/users \
  -H "Content-Type: application/json" \
  -d '{"username": "newshopper", "email": "newshopper@example.com", "password": "shopper2026"}'
```

Response — `201 Created` (no `password_hash` in the body):

```json
{
  "id": 11,
  "username": "newshopper",
  "email": "newshopper@example.com",
  "is_active": true,
  "role": "CUSTOMER",
  "created_at": "2026-08-15T12:00:00+00:00"
}
```

Request (missing/blank fields):

```sh
curl -X POST http://127.0.0.1:5000/users \
  -H "Content-Type: application/json" \
  -d '{"username": "", "email": "newshopper@example.com"}'
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "Username cannot be empty."
}
```

Request (password too weak):

```sh
curl -X POST http://127.0.0.1:5000/users \
  -H "Content-Type: application/json" \
  -d '{"username": "newshopper", "email": "newshopper@example.com", "password": "letters"}'
```

Response — `400 Bad Request`, naming the one rule that failed:

```json
{
  "error": "Bad Request",
  "message": "Password must be at least 8 characters long.",
  "code": "weak_password"
}
```

Request (missing/invalid JSON body):

```sh
curl -X POST http://127.0.0.1:5000/users
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "A valid JSON body is required."
}
```

Request (duplicate username or email):

```sh
curl -X POST http://127.0.0.1:5000/users \
  -H "Content-Type: application/json" \
  -d '{"username": "newshopper", "email": "someone-else@example.com", "password": "another-password"}'
```

Response — `409 Conflict`:

```json
{
  "error": "Conflict",
  "message": "Username already exists."
}
```

### GET /users/\<id\>

Returns the user matching `id`, without `password_hash`.

Request (found):

```sh
curl http://127.0.0.1:5000/users/1
```

Response — `200 OK`:

```json
{
  "id": 1,
  "username": "existing_user",
  "email": "existing_user@example.com",
  "is_active": true,
  "role": "CUSTOMER",
  "created_at": "2026-08-01T09:30:00+00:00"
}
```

Request (not found):

```sh
curl http://127.0.0.1:5000/users/999
```

Response — `404 Not Found`:

```json
{
  "error": "Not Found",
  "message": "User 999 was not found."
}
```

### POST /auth/login

Authenticates a user by `email` and `password` and returns an access/refresh token pair. Requires both fields in the body. See [Authentication](#authentication) for the full token lifecycle; this section covers the request/response shape.

Note that accounts created by `seed.sql` cannot log in — it stores placeholder strings such as `hash_budi_001` in `password_hash` rather than real Werkzeug hashes. Register through `POST /users` first.

```sh
curl -X POST http://127.0.0.1:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "the-users-password"}'
```

Response — `200 OK`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 604800,
  "user": {
    "id": 11,
    "username": "alice",
    "email": "alice@example.com",
    "is_active": true,
    "role": "CUSTOMER",
    "created_at": "2026-09-29T09:30:00+00:00"
  }
}
```

Missing or non-string credentials return `400 Bad Request`. A wrong password and an unknown email return the **identical** response, so the endpoint cannot be used to discover which accounts exist:

Response — `401 Unauthorized`:

```json
{
  "error": "Unauthorized",
  "message": "Invalid email or password.",
  "code": "invalid_credentials"
}
```

A deactivated account (`is_active = false`) is refused separately, since that is a state the account holder can act on rather than a credential mistake:

```json
{
  "error": "Unauthorized",
  "message": "This account has been deactivated.",
  "code": "account_inactive"
}
```

### POST /auth/refresh

Exchanges a **refresh** token for a new access/refresh pair. Send the refresh token — not the access token — in the header.

```sh
curl -X POST http://127.0.0.1:5000/auth/refresh \
  -H "Authorization: Bearer $REFRESH_TOKEN"
```

Response — `200 OK`: same shape as `POST /auth/login`.

The refresh token presented is revoked as part of the exchange, so store both halves of the response. Replaying a rotated token returns `401` with `"code": "token_revoked"`; an expired one returns `401` with `"code": "token_expired"` and `"token_type": "refresh"`, meaning the session is over.

### POST /auth/logout

Revokes the caller's tokens immediately, rather than leaving them usable until they expire. Send the **access** token in the header, and the refresh token in the body.

```sh
curl -X POST http://127.0.0.1:5000/auth/logout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"
```

Response — `200 OK`:

```json
{
  "message": "Logged out successfully.",
  "revoked": { "access": true, "refresh": true }
}
```

The body is optional, but omitting it leaves a working refresh token that can mint new access tokens, so the session would not really be over — `revoked.refresh` then reads `false`. A malformed value, or a refresh token belonging to a different account, is ignored rather than rejected; the response still reads `200` as long as the access token was revoked.

### GET /auth/me

Returns the account behind the access token. Useful for restoring a session after a page reload, and the cheapest way to check whether a stored token is still valid.

```sh
curl http://127.0.0.1:5000/auth/me \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response — `200 OK`: the user object, same shape as `GET /users/<id>`.

## CLI Commands

Both commands run inside the app context that `flask` provides, using `FLASK_APP=app.py` from `.flaskenv`.

### `flask check-db`

Verifies the live database connection and prints per-table row counts for the five Checkpoint 1 tables. Never prints the database password (the URL is rendered with `hide_password=True`, and any error message has the password scrubbed out).

```sh
flask check-db
```

Example output (success):

```
Target URI:  postgresql://postgres:***@localhost/revoshop_db
Database:    revoshop_db
Host:        localhost:5432
User:        postgres
Server:      PostgreSQL 16.3 on x86_64-pc-linux-gnu, ...
Connected:   revoshop_db

Row counts:
  users        10
  categories   4
  products     10
  orders       30
  order_items  56

Connection OK.
```

If the connection fails, the command prints the masked target URI, the error type and message with the password scrubbed, a hint to confirm PostgreSQL is running and the database exists, and exits with a non-zero status.

### `flask link-order-products`

Demonstrates the `orders` <-> `products` many-to-many relationship by extending order 4 (which already holds one product, Windbreaker Jacket) with two more products (Nike Air Max Running Shoes, Plain Cotton Combed T-Shirt), instead of creating a new order. This keeps the `queries.sql` "exactly three orders per user" integrity check green. Each inserted `order_items` row sets `unit_price` from the product's current price, and repeat runs are safe because inserts use `ON CONFLICT DO NOTHING` on the composite primary key. After inserting, it recomputes and commits order 4's `total_price` as the sum of `quantity * unit_price` over its association rows.

```sh
flask link-order-products
```

Example output:

```
Order 4 total_price: 995000.00
Order 4 products: [<Product 5 Windbreaker Jacket>, <Product 1 Nike Air Max Running Shoes>, <Product 2 Plain Cotton Combed T-Shirt>]
```

Running the command again reports the same total and the same three products, since the conflict clause prevents duplicate rows.

## Load Testing

`locustfile.py` simulates a sequential shopper journey against the local server. Each simulated user authenticates once, in `on_start`, then repeats the journey on a loop:

**Once per simulated user:**

0. `POST /users` then `POST /auth/login` — register a throwaway account and obtain an access/refresh token pair.

**Then, on a loop:**

1. `GET /products` — list all products, pick a random one.
2. `GET /products/<id>` — fetch that product.
3. `POST /orders` — place a 1-unit order for it, sending `Authorization: Bearer <access token>`. The order's owner comes from that token, so there is no `user_id` in the body.
4. `GET /orders/<id>` — fetch the order just created (also authenticated).
5. `POST /auth/refresh` — on roughly one journey in five, rotate the token pair.

Each user registers its own account rather than reusing a seeded one, because accounts from `seed.sql` cannot log in: it stores placeholder strings such as `hash_budi_001` in `password_hash` instead of real Werkzeug hashes. Set `LOCUST_EMAIL` and `LOCUST_PASSWORD` to share one existing account instead (closer to a hot-key scenario than to real traffic).

The refresh step is included deliberately. Rotation writes a row to `token_blocklist`, and every authenticated request reads that table, so the refresh path has a database cost that belongs in the measurements rather than being assumed cheap.

The Statistics table groups per-id requests under the fixed labels `/products/[id]` and `/orders/[id]` (via Locust's `name=` parameter) rather than one row per distinct id, so a run's results fit in a handful of rows: `/users (register)`, `/auth/login`, `GET /products`, `/products/[id]`, `POST /orders`, `/orders/[id]`, and `/auth/refresh`.

An expired access token on `POST /orders` is the one failure treated as recoverable: the journey refreshes and carries on, rather than counting the server as broken. Every other non-201 — including a 400 from insufficient stock — is recorded as a failure, so stock depletion shows up in the numbers instead of being hidden.

### Running it

The Flask server must already be running (`flask run` or `python app.py`) before starting Locust; `locustfile.py` sends real HTTP requests to it, it does not import or call the app in-process.

Two things have to be set on the server before a run:

**1. Point `DATABASE_URL` at a throwaway database.** A run commits real orders, deducts real stock, registers one account per simulated user, and writes a `token_blocklist` row per refresh. None of that is reverted afterwards. Any database you are willing to lose will do — a second local Postgres, a separate Supabase project, whatever you have — as long as it is not the one holding data you care about.

**Apply the migrations to it first**, or the run fails in a confusing way:

```sh
flask db upgrade
```

Every authenticated request reads `token_blocklist`, so against a database missing that table (added in revision `56e0d1e07c3f`) login and refresh answer `500` and the journey never gets a token.

**2. Turn rate limiting off.** All the simulated users come from one IP, so the limiter sees a single client making hundreds of requests a second. Leave it on and registration caps out after a handful of users and the rest never authenticate — the run measures nothing but `429`s.

```powershell
# PowerShell — overrides apply to this terminal session only
$env:DATABASE_URL="<your throwaway database URL>"
$env:RATELIMIT_ENABLED="false"
flask db upgrade
flask run
```

A local Postgres is worth preferring over a hosted one here: network latency to a remote database lands in every measurement, so the numbers end up describing the connection more than the application.

Then in a second terminal, start Locust:

```sh
locust -f locustfile.py --host=http://127.0.0.1:5000
```

Then open `http://localhost:8089`, type a number of users and a spawn (ramp-up) rate — e.g. 200 users at 5/second — and click **Start**. There is no scripted ramp-up shape in this file, so whatever you type in the web UI is exactly what runs.

To run headless (no web UI) instead:

```sh
locust -f locustfile.py --host=http://127.0.0.1:5000 \
    --users 200 --spawn-rate 10 --run-time 2m --headless
```

### After a run

A run leaves four kinds of row behind in whichever database it hit: orders and their line items, one account per simulated user, and a `token_blocklist` row per refresh. Stock is left wherever the orders pushed it, which for a long run is often zero. To reset for the next run, connected to that database:

```sql
TRUNCATE order_items, orders RESTART IDENTITY CASCADE;
DELETE FROM token_blocklist;
DELETE FROM users WHERE username LIKE 'locust\_%';
-- then restore stock, e.g.
UPDATE products SET stock_quantity = 50, is_delete = false;
```

Dropping and re-creating the database works too, as long as you remember the two steps that follow: `flask db upgrade` to rebuild the schema, and re-seeding products, since `GET /products` returning an empty list fails the first step of the journey.

Note that `DELETE FROM users` only removes the accounts this file created (`locust_…`); the `ON DELETE CASCADE` on `token_blocklist.user_id` clears their tokens either way.

## Screenshots

All images live in the [`images/`](images/) folder.

### API requests (Postman)

Each HTTP method is exercised against the local server:

**GET**

- Home / health check — ![GET /](images/Get_home.jpg)
- List products — ![GET /products](images/GET_products.jpg)
- Single product — ![GET /products/<id>](images/GET_products_id.jpg)
- List categories — ![GET /categories](images/GET_categories.jpg)
- Single category (with its products) — ![GET /categories/<id>](images/GET_categories_id.jpg)
- List a user's orders — ![GET /orders](images/GET_orders.jpg)
- Single order (with line items) — ![GET /orders/<id>](images/GET_orders_id.jpg)
- Single user — ![GET /users/<id>](images/GET_users_id.jpg)
- User not found (404) — ![GET user not found](images/GET_user_not_found.jpg)

**POST**

- Create product — ![POST /products](images/POST_products.jpg)
- Create category — ![POST /categories](images/POST_categories.jpg)
- Create order — ![POST /orders](images/POST_orders.jpg)
- Register user — ![POST /users](images/POST_user.jpg)
- Login — ![POST /auth/login](images/POST_auth_login.jpg)

**PUT**

- Update product — ![PUT /products/<id>](images/PUT_products_id.jpg)
- Update category — ![PUT /categories/<id>](images/PUT_categories_id.jpg)

**DELETE**

- Delete product — ![DELETE /products/<id>](images/DELETE_products_id.jpg)
- Delete category — ![DELETE /categories/<id>](images/DELETE_categories_id.jpg)
- Delete order — ![DELETE /orders/<id>](images/DELETE_orders_id.jpg)

### Database (pgAdmin)

- `revoshop_db` public schema and tables — ![revoshop_db tables](images/revoshop_db%20-%20postgres%20-%20public.png)
- Server / database tree — ![revoshop_db server tree](images/revoshop_db%20server%20tree.jpg)
- `order_items` association table exists — ![order_items table](images/order_items%20association%20table%20exists.jpg)
- Many-to-many: one order linked to multiple products — ![many-to-many 1](images/order_items%20with%20at%20least%20one%20order%20linked%20to%20multiple%20products%20(many-to-many)%201.jpg) ![many-to-many 2](images/order_items%20with%20at%20least%20one%20order%20linked%20to%20multiple%20products%20(many-to-many)%202.jpg)
- `role` column added to `users` (migration) — ![role column](images/role%20column%20added%20to%20users%20table.jpg)

### Load testing (Locust)

- 200-user run, statistics — ![Locust 200 users](images/Locust_test_200_users.jpg)
- Charts — ![Locust charts 1](images/Locust_test_200_users_charts_1.jpg) ![Locust charts 2](images/Locust_test_200_users_charts_2.jpg)
- Logs — ![Locust logs](images/Locust_test_200_users_logs.jpg)
