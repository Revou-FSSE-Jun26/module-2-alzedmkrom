# RevoShop Database

PostgreSQL database design for the RevoShop checkpoint. It models users, product categories, products, orders, and the line items connecting orders to products.

## Project Files

- `schema.sql` — creates the database tables, constraints, relationships, and indexes.
- `seed.sql` — inserts realistic sample data into every table.
- `queries.sql` — contains filtering, sorting, limiting, and data-integrity queries.

## Setup

1. Install PostgreSQL 14 or newer. During installation, set and securely save the password for the `postgres` superuser.
2. Open a terminal and verify the PostgreSQL installation:
   ```sh
   psql -U postgres -c "SELECT version();"
   ```
   Enter the `postgres` password when prompted. A successful command prints the installed PostgreSQL version.
3. Install DBeaver, pgAdmin, or another PostgreSQL client.
4. In the database client, connect to PostgreSQL's default `postgres` database with the `postgres` username and the password created during installation.
5. From `schema.sql`, execute only:
   ```sql
   CREATE DATABASE revoshop_db;
   ```
6. Open a new SQL editor connected to `revoshop_db`.
7. Execute the remainder of `schema.sql`, starting with `CREATE TABLE users`.
8. Execute `seed.sql` to populate all tables.
9. Execute `queries.sql` to test the data and relationships.

PostgreSQL does not automatically switch connections after `CREATE DATABASE`, so reconnecting in step 6 is required. Run the seed script against a new, empty database because its order-item references expect generated IDs to begin at 1.

## Tables and Relationships

- `users` has many `orders`.
- `categories` has many `products`.
- `orders` and `products` have a many-to-many relationship through `order_items`.
- `order_items` uses `(order_id, product_id)` as its composite primary key.
- `unit_price` stores the product price at the time an order is created.

## Expected Seed Results

| Table | Rows |
|---|---:|
| `users` | 10 |
| `categories` | 4 |
| `products` | 10 |
| `orders` | 30 |
| `order_items` | 54 |

The sample password hashes are placeholders for database testing only. The `users` table intentionally has no `role` column because roles are reserved for a later schema-migration checkpoint.
