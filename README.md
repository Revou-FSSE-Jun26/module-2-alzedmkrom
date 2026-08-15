# RevoShop

A Flask + SQLAlchemy application layer built on top of the existing, already-populated `revoshop_db` PostgreSQL database from Checkpoint 1. It exposes hardcoded product endpoints, database-backed user registration/retrieval endpoints, a Flask-Migrate history that adds a `role` column to `users`, and two `flask` CLI commands for connection verification and many-to-many demonstration data.

Full CRUD, authentication/authorization enforcement, and deployment are out of scope for this checkpoint.

## Project Files

- `schema.sql`, `seed.sql`, `queries.sql` — Checkpoint 1 database design, sample data, and verification queries. Unchanged by this checkpoint.
- `config.py` — the `Config` class (database URI, `SECRET_KEY`).
- `extensions.py` — the module-level `app`, `db = SQLAlchemy(app)`, and `migrate = Migrate(app, db)`.
- `models.py` — `User`, `Category`, `Product`, `Order`, and the `order_items` association table.
- `routes.py` — `products_bp` (hardcoded) and `users_bp` (database-backed).
- `errors.py` — JSON error handlers for 400/404/405/500.
- `cli.py` — `flask check-db` and `flask link-order-products`.
- `app.py` — entry point; registers blueprints and runs the dev server.
- `migrations/` — the Flask-Migrate environment and revision history.

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

```sh
pip install -r requirements.txt
```

This installs Flask, Flask-SQLAlchemy, Flask-Migrate, SQLAlchemy, alembic, `psycopg2-binary`, and `python-dotenv` at the versions pinned in `requirements.txt`.

### 3. Configure the connection

There are two environment files:

- **`.flaskenv`** (committed, holds no secrets) — sets `FLASK_APP=app.py` and `FLASK_DEBUG=1`, which is what lets `flask run`, `flask db ...`, and the custom `flask` commands find the app with no extra flags.
- **`.env`** (gitignored, must never be committed) — copy `.env.example` to `.env` and fill in `SECRET_KEY`:

  ```sh
  cp .env.example .env
  ```

  Generate a value for `SECRET_KEY` with:

  ```sh
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

  `SECRET_KEY` is the only environment variable this project reads; if `.env` is absent or the variable is unset, `config.py` falls back to a hardcoded development value (`dev-secret-key-change-me`).

**The database connection itself is not read from the environment.** `SQLALCHEMY_DATABASE_URI` is a literal string in `config.py`:

```python
SQLALCHEMY_DATABASE_URI = "postgresql://postgres:alzedsql22@localhost/revoshop_db"
```

This is a deliberate simplification for this local-only checkpoint against the `revoshop_db` database created in Checkpoint 1. To point the app at a different PostgreSQL user, password, host, or database name, edit that line in `config.py` directly, using the same `postgresql://user:password@host/dbname` form.

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

The migration history is baselined on top of the already-populated `revoshop_db` rather than recreating it. The `migrations/versions/` directory contains three revisions, applied in this order:

| Order | Revision ID | File | Description |
|---|---|---|---|
| 1 | `b0725bc519d7` | `b0725bc519d7_baseline_checkpoint_1_schema.py` | Baseline: describes the five Checkpoint 1 tables, the two case-insensitive unique indexes, and the three foreign-key indexes exactly as they already exist. **Stamped, not upgraded**, against the populated database. |
| 2 | `44a808644adc` | `44a808644adc_add_unique_constraints_to_users_.py` | Adds plain unique constraints (`users_username_key`, `users_email_key`) on `users.username`/`users.email`, on top of the existing case-insensitive functional indexes. |
| 3 | `67d9a832861f` | `67d9a832861f_add_role_to_users.py` | Adds `users.role` (`VARCHAR(50) NOT NULL`) with a server default of `'CUSTOMER'`, backfilling all existing rows in the same statement. This is the current head. |

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

Because `revoshop_db` already contains the five tables with 10 users, 4 categories, 10 products, 30 orders, and 54 order items, running the baseline revision's `upgrade()` would try to `CREATE TABLE` tables that already exist and fail. Instead, the baseline is recorded as already applied, without executing any DDL:

```sh
flask db stamp b0725bc519d7
```

Then apply the remaining revisions normally:

```sh
flask db upgrade
```

This brings `revoshop_db` to `67d9a832861f` (the current head) while preserving every existing row.

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

and confirm the row counts still read 10 / 4 / 10 / 30 / 54 on a fresh Checkpoint 1 seed (54 rising to 56 after `flask link-order-products` runs). The `users` count may read higher than 10 if `/users/register` has been exercised since seeding; that is expected and does not indicate data loss, since the original 10 rows are still present. Re-running `queries.sql` in a database client should still return no rows from its integrity checks.

## Endpoints

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

### GET /products

Returns the complete hardcoded product list. Issues no SQL.

Request:

```sh
curl http://127.0.0.1:5000/products
```

Response — `200 OK`:

```json
[
  {
    "id": 1,
    "name": "Nike Air Max Running Shoes",
    "category": "Footwear",
    "price": 850000.0,
    "stock_quantity": 50
  },
  {
    "id": 2,
    "name": "Plain Cotton Combed T-Shirt",
    "category": "Apparel",
    "price": 75000.0,
    "stock_quantity": 200
  }
  // ... 8 more products
]
```

### GET /products/\<id\>

Returns the single hardcoded product matching `id`.

Request (found):

```sh
curl http://127.0.0.1:5000/products/1
```

Response — `200 OK`:

```json
{
  "id": 1,
  "name": "Nike Air Max Running Shoes",
  "category": "Footwear",
  "price": 850000.0,
  "stock_quantity": 50
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

### POST /users/register

Creates a new user account. Validates the body, checks for a case-insensitive duplicate on `username`/`email`, hashes the password with Werkzeug, and persists the row.

Request (success):

```sh
curl -X POST http://127.0.0.1:5000/users/register \
  -H "Content-Type: application/json" \
  -d '{"username": "newshopper", "email": "newshopper@example.com", "password": "a-strong-password"}'
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
curl -X POST http://127.0.0.1:5000/users/register \
  -H "Content-Type: application/json" \
  -d '{"username": "", "email": "newshopper@example.com"}'
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "Missing or blank field(s): username, password"
}
```

Request (missing/invalid JSON body):

```sh
curl -X POST http://127.0.0.1:5000/users/register
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
curl -X POST http://127.0.0.1:5000/users/register \
  -H "Content-Type: application/json" \
  -d '{"username": "newshopper", "email": "someone-else@example.com", "password": "another-password"}'
```

Response — `409 Conflict`:

```json
{
  "error": "Conflict",
  "message": "A user with that username or email already exists."
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
  order_items  54

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
