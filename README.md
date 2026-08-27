# RevoShop

A Flask + SQLAlchemy application layer built on top of the existing, already-populated `revoshop_db` PostgreSQL database from Checkpoint 1. It exposes database-backed endpoints for products, categories, orders, and user registration/retrieval, a Flask-Migrate history that adds a `role` column to `users` and an `is_delete` soft-delete column to both `products` and `orders`, and two `flask` CLI commands for connection verification and many-to-many demonstration data.

Full CRUD, authentication/authorization enforcement, and deployment are out of scope for this checkpoint.

## Project Files

- `schema.sql`, `seed.sql`, `queries.sql` — Checkpoint 1 database design, sample data, and verification queries. Unchanged by this checkpoint.
- `config.py` — the `Config` class (database URI, `SECRET_KEY`).
- `extensions.py` — the module-level `app`, `db = SQLAlchemy(app)`, and `migrate = Migrate(app, db)`.
- `models.py` — `User`, `Category`, `Product`, `Order`, and the `order_items` association table.
- `routes.py` — `home_bp`, `products_bp`, `categories_bp`, `orders_bp`, and `users_bp`, all database-backed.
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
- **`.env`** (gitignored, must never be committed) — copy `.env.example` to `.env` and fill in real values:

  ```sh
  cp .env.example .env
  ```

  `config.py` calls `load_dotenv()` on import, so every value below comes from `.env` (or the real shell/host environment in production, which `python-dotenv` never overrides). There is no hardcoded fallback for any of them: a missing `.env` fails loudly at startup with a `KeyError` instead of silently connecting to the wrong database.

  - **`DATABASE_URL`** — the PostgreSQL connection string for `revoshop_db`, in `postgresql://user:password@host/dbname` form. Edit this to point at a different user, password, host, or database name.
  - **`SECRET_KEY`** — used by Flask for session signing. Generate a value with:

    ```sh
    python -c "import secrets; print(secrets.token_hex(32))"
    ```

  - **`FLASK_DEBUG`** — `true` to enable Flask's debug mode (auto-reload, interactive debugger) when running via `python app.py`. Set to `false` outside local development. (`flask run` reads its own `FLASK_DEBUG` from `.flaskenv` instead, independently of this one.)

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

The migration history is baselined on top of the already-populated `revoshop_db` rather than recreating it. The `migrations/versions/` directory contains five revisions, applied in this order:

| Order | Revision ID | File | Description |
|---|---|---|---|
| 1 | `b0725bc519d7` | `b0725bc519d7_baseline_checkpoint_1_schema.py` | Baseline: describes the five Checkpoint 1 tables, the two case-insensitive unique indexes, and the three foreign-key indexes exactly as they already exist. **Stamped, not upgraded**, against the populated database. |
| 2 | `44a808644adc` | `44a808644adc_add_unique_constraints_to_users_.py` | Adds plain unique constraints (`users_username_key`, `users_email_key`) on `users.username`/`users.email`, on top of the existing case-insensitive functional indexes. |
| 3 | `67d9a832861f` | `67d9a832861f_add_role_to_users.py` | Adds `users.role` (`VARCHAR(50) NOT NULL`) with a server default of `'CUSTOMER'`, backfilling all existing rows in the same statement. |
| 4 | `48a1dad68d30` | `48a1dad68d30_add_is_active_to_products.py` | Adds `products.is_active` (`BOOLEAN NOT NULL`) with a server default of `true`, backfilling all existing rows in the same statement. Superseded by revision 5 below. |
| 5 | `e4e6cb9cdcda` | `e4e6cb9cdcda_add_order_is_delete_rename_product_is_.py` | Adds `orders.is_delete` (`BOOLEAN NOT NULL`, default `false`). Renames `products.is_active` to `products.is_delete`, inverting both the column's polarity and its data (`is_delete = NOT is_active`) so both tables use the same `is_delete` naming/meaning. This is the current head. |

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
