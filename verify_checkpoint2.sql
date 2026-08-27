-- Checkpoint 2 verification queries
--
-- These queries confirm the changes made after the Checkpoint 1 baseline:
-- the `role` column added to `users` (Requirement 8), the order 4
-- many-to-many association rows (Requirement 9), and a re-run of the
-- `queries.sql` integrity checks that must still return no rows after the
-- migrations and the `flask link-order-products` command have run.
--
-- This file is additive documentation only. `schema.sql`, `seed.sql`, and
-- `queries.sql` are left unchanged.

-- ---------------------------------------------------------------------------
-- 1. Confirm the `users.role` column exists and shows values.
-- Expected: 10 rows, one per seeded user, each with a non-empty `role`.
-- ---------------------------------------------------------------------------
SELECT id, username, role
FROM users
ORDER BY id;

-- ---------------------------------------------------------------------------
-- 2. Confirm the `role` values backfilled by the migrations.
-- Expected: a single group, `'USER'`, with COUNT(*) = 10 -- revision 3
-- (67d9a832861f) backfilled every existing row with `'CUSTOMER'` via its
-- server default, then revision 4 (d67af913472c) updated the server default
-- to `'USER'` and rewrote the existing `'CUSTOMER'` rows to `'USER'`.
-- ---------------------------------------------------------------------------
SELECT role, COUNT(*) AS user_count
FROM users
GROUP BY role
ORDER BY role;

-- No user should have a null role. Expected: 0.
SELECT COUNT(*) AS null_role_count
FROM users
WHERE role IS NULL;

-- ---------------------------------------------------------------------------
-- 3. Show order 4's association rows, joined with products, to demonstrate
-- the many-to-many link populated by `flask link-order-products`.
-- Expected: 3 rows (the original product plus the two products added by
-- the command), each with a product name, quantity, and unit price.
-- ---------------------------------------------------------------------------
SELECT
    oi.order_id,
    oi.product_id,
    p.name,
    oi.quantity,
    oi.unit_price
FROM order_items AS oi
JOIN products AS p ON p.id = oi.product_id
WHERE oi.order_id = 4
ORDER BY oi.product_id;

-- ---------------------------------------------------------------------------
-- 4. Confirm order 4 is linked to more than one distinct product.
-- Expected: TRUE (distinct_product_count > 1).
-- ---------------------------------------------------------------------------
SELECT
    COUNT(DISTINCT product_id) AS distinct_product_count,
    COUNT(DISTINCT product_id) > 1 AS has_multiple_products
FROM order_items
WHERE order_id = 4;

-- ---------------------------------------------------------------------------
-- 5. Re-run of the `queries.sql` integrity checks, to confirm the role
-- migration and the `link-order-products` command did not break existing
-- data integrity.
-- ---------------------------------------------------------------------------

-- 5a. Orders without any items. Expected: no rows.
SELECT o.id, o.user_id, o.total_price, o.status
FROM orders AS o
LEFT JOIN order_items AS oi ON oi.order_id = o.id
WHERE oi.order_id IS NULL
ORDER BY o.id;

-- 5b. Orders whose stored total does not match their item total.
-- This is the stored-vs-calculated `total_price` check referenced by
-- Requirement 9.6: order 4's total must have been recomputed after the
-- association rows were added, so this must still return no rows for every
-- order, including order 4. Expected: no rows (empty result set = pass).
SELECT
    o.id AS order_id,
    o.total_price AS stored_total,
    COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS calculated_total,
    o.total_price - COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS difference
FROM orders AS o
LEFT JOIN order_items AS oi ON oi.order_id = o.id
GROUP BY o.id, o.total_price
HAVING o.total_price <> COALESCE(SUM(oi.quantity * oi.unit_price), 0)
ORDER BY o.id;

-- 5c. Usernames or emails duplicated with different letter casing.
-- Expected because of the case-insensitive unique indexes: no rows.
SELECT 'username' AS duplicate_field, LOWER(username) AS duplicate_value, COUNT(*) AS duplicate_count
FROM users
GROUP BY LOWER(username)
HAVING COUNT(*) > 1
UNION ALL
SELECT 'email', LOWER(email), COUNT(*)
FROM users
GROUP BY LOWER(email)
HAVING COUNT(*) > 1;

-- 5d. Unexpected order statuses. Expected: no rows.
SELECT id, user_id, status
FROM orders
WHERE status NOT IN ('PENDING', 'PROCESSING', 'SHIPPED', 'COMPLETED', 'CANCELLED')
ORDER BY id;

-- 5e. Table row counts, updated for the rows added by
-- `flask link-order-products` (order_items grows from 54 to 56).
-- Expected: users 10, categories 4, products 10, orders 30, order_items 56.
SELECT 'users' AS table_name, COUNT(*) FROM users
UNION ALL
SELECT 'categories', COUNT(*) FROM categories
UNION ALL
SELECT 'products', COUNT(*) FROM products
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'order_items', COUNT(*) FROM order_items;
