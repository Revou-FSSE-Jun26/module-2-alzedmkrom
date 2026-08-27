SELECT id, username, email, created_at
FROM users
WHERE email LIKE '%@mail.com'
ORDER BY created_at DESC
LIMIT 3;

SELECT name, description 
FROM categories
WHERE description LIKE '%and%'
ORDER BY name ASC
LIMIT 2;

SELECT name, price, stock_quantity 
FROM products
WHERE stock_quantity > 50 AND category_id != 1
ORDER BY price ASC
LIMIT 3;

SELECT id, user_id, total_price, status 
FROM orders
WHERE status = 'COMPLETED'
ORDER BY total_price DESC
LIMIT 3;

SELECT order_id, product_id, quantity 
FROM order_items
WHERE quantity = 1
ORDER BY order_id DESC
LIMIT 4;

-- Edge-case and data-integrity queries
-- 1. Orders without any items. Expected with valid seed data: no rows.
SELECT o.id, o.user_id, o.total_price, o.status
FROM orders AS o
LEFT JOIN order_items AS oi ON oi.order_id = o.id
WHERE oi.order_id IS NULL
ORDER BY o.id;

-- 2. Orders whose stored total does not match their item total.
-- Expected with valid seed data: no rows.
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

-- 3. Users who do not have exactly three orders.
-- Expected with the current seed data: no rows.
SELECT u.id, u.username, COUNT(o.id) AS order_count
FROM users AS u
LEFT JOIN orders AS o ON o.user_id = u.id
GROUP BY u.id, u.username
HAVING COUNT(o.id) <> 3
ORDER BY u.id;

-- 4. Usernames or emails duplicated with different letter casing.
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

-- 5. Order prices that differ from the product's current price.
-- Such rows can be valid if a product price changed after checkout.
SELECT
    oi.order_id,
    oi.product_id,
    oi.unit_price AS ordered_price,
    p.price AS current_price
FROM order_items AS oi
JOIN products AS p ON p.id = oi.product_id
WHERE oi.unit_price <> p.price
ORDER BY oi.order_id, oi.product_id;

-- 6. Products that have never been ordered.
SELECT p.id, p.name, p.stock_quantity
FROM products AS p
LEFT JOIN order_items AS oi ON oi.product_id = p.id
WHERE oi.product_id IS NULL
ORDER BY p.id;

-- 7. Test the exact boundary excluded by the existing stock_quantity > 50 query.
SELECT id, name, price, stock_quantity
FROM products
WHERE stock_quantity = 50
ORDER BY price;

-- 8. Unexpected order statuses. Expected with valid seed data: no rows.
SELECT id, user_id, status
FROM orders
WHERE status NOT IN ('PENDING', 'PROCESSING', 'SHIPPED', 'COMPLETED', 'CANCELLED', 'RETURNED', 'REFUNDED')
ORDER BY id;

SELECT 'users' AS table_name, COUNT(*) FROM users
UNION ALL
SELECT 'categories', COUNT(*) FROM categories
UNION ALL
SELECT 'products', COUNT(*) FROM products
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'order_items', COUNT(*) FROM order_items;

SELECT
    oi.order_id,
    p.id AS product_id,
    p.name AS product_name,
    oi.quantity,
    oi.unit_price
FROM order_items AS oi
JOIN products AS p ON p.id = oi.product_id
WHERE oi.order_id = 4
ORDER BY p.id;

SELECT order_id, COUNT(*) AS product_count
FROM order_items
GROUP BY order_id
HAVING COUNT(*) > 1
ORDER BY order_id;