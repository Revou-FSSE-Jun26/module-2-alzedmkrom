# RevoShop

A Flask + SQLAlchemy application layer built on top of the existing, already-populated `revoshop_db` PostgreSQL database from Checkpoint 1. It exposes database-backed endpoints for products, categories, orders, and user registration/retrieval, a Flask-Migrate history that adds a `role` column to `users` and an `is_delete` soft-delete column to both `products` and `orders`, and `flask` CLI commands for connection verification and many-to-many demonstration data.

Real session/token authentication and deployment are out of scope for this checkpoint (JWT is optional/exploratory only); everything runs locally.

## Overview

RevoShop is the backend for a small online store. It manages a catalog of **products** grouped into **categories**, lets **users** register and place **orders**, and records each order's line items in an `order_items` association table that links orders to products (many-to-many, with per-line `quantity` and `unit_price`). It is a Flask + SQLAlchemy REST API returning JSON, sitting on top of the PostgreSQL database (`revoshop_db`) designed in Checkpoint 1.

## Features Implemented

- **Full CRUD for products** — create, list, retrieve, update, and delete (`POST`/`GET`/`GET <id>`/`PUT`/`DELETE /products`).
- **Full CRUD for categories** — create, list, retrieve (with the category's products), update, and delete (`/categories`).
- **Full CRUD for orders** — place an order, list a user's orders, retrieve one order with its line items and product details, update status, and delete (`/orders`).
- **User registration, retrieval, and a placeholder login** — `POST /users`, `GET /users/<id>`, `POST /auth/login`. Passwords are hashed with Werkzeug and never returned.
- **Many-to-many between orders and products through `order_items`** — each order line stores its own `quantity` and the `unit_price` captured at order time, so an order is a faithful record of what was actually charged. `flask link-order-products` demonstrates one order linked to multiple products.
- **Data validation** — every write endpoint validates required fields, types, ranges, and lengths, returning `400`/`422` with a clear message on bad input, and `409` on conflicts (duplicate category/user, delete blocked by references).
- **Error handling with `try`/`except`** — all database writes are wrapped so an `IntegrityError` maps to `409` and any other `SQLAlchemyError` rolls back and maps to `500`, with the internal detail logged (never leaked). Framework 404/405 responses are also returned as JSON.
- **Deletion guard on products** — `DELETE /products/<id>` will not remove a product that still has **active** orders (any non-finalized status): it returns `409`. A product whose orders are all finalized is soft-deleted (`is_delete = true`) to preserve order history, and a product never ordered is hard-deleted.
- **Stock management** — placing an order decrements product stock (and rejects an order that exceeds available stock); cancelling/returning/refunding an order restores it.
- **Soft delete for orders** — `DELETE /orders/<id>` sets `is_delete = true` instead of removing the row, so financial/order history is never destroyed.
- **Automated tests** — a `pytest` suite (`tests/`) covers all Category CRUD endpoints plus users, products, and orders, on happy-path and error cases, against an isolated test database.
- **Load testing** — a `locustfile.py` simulates a concurrent shopper journey (browse → view → order → view order) against a dedicated `revoshop_test` database.

## Technologies Used

- **Flask** — web framework and routing (via blueprints).
- **SQLAlchemy** — ORM and query layer.
- **Flask-Migrate** (Alembic) — version-controlled schema migrations.
- **PostgreSQL** — the relational database (`revoshop_db`).
- **pgAdmin** — GUI for inspecting the local database and tables.
- **pytest** — the automated test suite.
- **Locust** — load/performance testing.
- **python-dotenv** — loads configuration and secrets from `.env`.
- **Werkzeug** — password hashing (ships with Flask).
- **psycopg2** — PostgreSQL driver.

## Project Files

- `schema.sql`, `seed.sql`, `queries.sql` — Checkpoint 1 database design, sample data, and verification queries. Unchanged by this checkpoint.
- `config.py` — the `Config` class (database URI, `SECRET_KEY`).
- `extensions.py` — the module-level `app`, `db = SQLAlchemy(app)`, and `migrate = Migrate(app, db)`.
- `models.py` — `User`, `Category`, `Product`, `Order`, and the `order_items` association table.
- `routes.py` — `home_bp`, `products_bp`, `categories_bp`, `orders_bp`, and `users_bp`, all database-backed.
- `errors.py` — JSON error handlers for 400/404/405/500.
- `cli.py` — `flask check-db` and `flask link-order-products`.
- `locustfile.py` — Locust load test simulating a shopper journey (list products, view one, place an order, view that order).
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

Places an order. Requires `user_id` (integer referencing an existing user) and a non-empty `items` array, each item an object with `product_id` (existing product) and `quantity` (integer > 0, not exceeding the product's current stock). The same `product_id` cannot appear twice. The server sets `status` to `PENDING` and computes `total_price` itself; `unit_price` is captured from each product's current price, and each product's `stock_quantity` is decremented. If any item fails validation the whole order is rejected (all-or-nothing).

```sh
curl -X POST http://127.0.0.1:5000/orders \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "items": [{"product_id": 3, "quantity": 2}, {"product_id": 6, "quantity": 1}]}'
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
  -d '{"user_id": 1, "items": [{"product_id": 5, "quantity": 9999}]}'
```

Response — `400 Bad Request`:

```json
{
  "error": "Bad Request",
  "message": "items[0].product_id 5 has only 30 in stock, which is less than the requested quantity (9999)."
}
```

### GET /orders

Returns the orders belonging to one user, ordered by `id`. `user_id` is a **required** query parameter (there is no session/token auth, so the caller names the user directly). Soft-deleted orders are excluded by default; pass `&include_deleted=true` to include them.

```sh
curl "http://127.0.0.1:5000/orders?user_id=1"
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

Creates a new user account. Validates the body, checks for a case-insensitive duplicate on `username`/`email`, hashes the password with Werkzeug, and persists the row. An optional `role` (string, 50 chars or fewer) may be supplied; if omitted it defaults to `CUSTOMER`.

Request (success):

```sh
curl -X POST http://127.0.0.1:5000/users \
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

Authenticates a user by `email` and `password`. This is a placeholder for this checkpoint: on success it returns `200 OK` with the user's data (no token or session is issued — session/token auth is out of scope, see the note under `create_order`). Requires both `email` and `password` in the body.

```sh
curl -X POST http://127.0.0.1:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "budi@mail.com", "password": "the-users-password"}'
```

Response — `200 OK`:

```json
{
  "id": 1,
  "username": "budi_santoso",
  "email": "budi@mail.com",
  "is_active": true,
  "role": "CUSTOMER",
  "created_at": "2026-08-01T09:30:00+00:00"
}
```

Request (missing credentials) returns `400 Bad Request`. Wrong email or password returns:

Response — `401 Unauthorized`:

```json
{
  "error": "Unauthorized",
  "message": "Invalid email or password."
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

`locustfile.py` simulates a sequential shopper journey against the local server, one pass per simulated user, repeated on a loop:

1. `GET /products` — list all products, pick a random one that is in stock and not soft-deleted.
2. `GET /products/<id>` — fetch that product.
3. `POST /orders` — place a 1-unit order for it, as an existing seeded user (`user_id=1`; there is no session/token auth in this project, so `user_id` is just a request body field — see the "Logged-in user" note under `create_order` in `routes.py`).
4. `GET /orders/<id>` — fetch the order just created.

The Statistics table groups `GET /products/<id>` and `GET /orders/<id>` under the fixed labels `/products/[id]` and `/orders/[id]` (via Locust's `name=` parameter) rather than one row per distinct id, so a full run's results fit in exactly four rows: `GET /products`, `GET /products/[id]`, `POST /orders`, `GET /orders/[id]`.

### Running it

The Flask server must already be running (`flask run` or `python app.py`) before starting Locust; `locustfile.py` sends real HTTP requests to it, it does not import or call the app in-process.

**Use a dedicated test database** so Locust orders and stock changes never touch your main `revoshop_db` data. Point `DATABASE_URL` at `revoshop_test` before starting the server (see `.env.example` for one-time setup instructions):

```powershell
# PowerShell — override DATABASE_URL for this terminal session only
$env:DATABASE_URL="postgresql://postgres:your_password@localhost/revoshop_test"
flask run
```

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

Because Locust hits `revoshop_test`, your main `revoshop_db` is completely unaffected. If you want a clean `revoshop_test` for the next run, truncate the orders and order_items tables and reset stock:

```sql
-- in psql or pgAdmin, connected to revoshop_test
TRUNCATE order_items, orders RESTART IDENTITY;
UPDATE products SET stock_quantity = seed_value, is_delete = false;
```

Or simply drop and re-create `revoshop_test` from scratch — it only has seed data (no real user orders), so nothing important is lost.

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
