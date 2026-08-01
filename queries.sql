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

