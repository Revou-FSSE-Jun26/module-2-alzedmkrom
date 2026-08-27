INSERT INTO users (username, email, password_hash)
VALUES
    ('budi_santoso',  'budi@mail.com',  'hash_budi_001'),
    ('siti_rahma',    'siti@mail.com',  'hash_siti_002'),
    ('ahmad_fauzi',   'ahmad@mail.com', 'hash_ahmad_003'),
    ('rina_dewi',     'rina@mail.com',  'hash_rina_004'),
    ('doni_pratama',  'doni@mail.com',  'hash_doni_005'),
	('eka_saputra',   'eka@mail.com',   'hash_eka_006'),
    ('dewi_lestari',  'dewi@mail.com',  'hash_dewi_007'),
    ('rizky_hidayat', 'rizky@mail.com', 'hash_rizky_008'),
    ('mega_utami',    'mega@mail.com',  'hash_mega_009'),
    ('fajar_nugroho', 'fajar@mail.com', 'hash_fajar_010');

INSERT INTO categories (name, description)
VALUES
    ('Apparel', 'Collection of t-shirts, pants, jackets, and other garments'),
    ('Footwear', 'Athletic shoes, casual shoes, and socks'),
    ('Accessories', 'Outfit complements such as hats, sunglasses, watches, and belts'),
    ('Bags', 'Backpacks, messenger bags, and travel storage containers');

INSERT INTO products (name, category_id, description, price, stock_quantity)
VALUES
    ('Nike Air Max Running Shoes', 2, 'Lightweight and comfortable for jogging',          850000.00,  50),
    ('Plain Cotton Combed T-Shirt',1, 'Breathable material, available in various colors',  75000.00, 200),
    ('Fleece Jogger Pants',        1, 'Warm for winter sports and activities',            195000.00,  80),
    ('Unisex Baseball Cap',        3, 'Suitable for outdoor activities',                  120000.00, 150),
    ('Windbreaker Jacket',         1, 'Windproof, lightweight material',                  450000.00,  30),
    ('Sports Socks 3-Pack',        2, 'Moisture-wicking, perfect for running',             55000.00, 300),
    ('Waterproof Backpack',        4, '20L capacity, safe for laptops and rain',          320000.00,  60),
    ('UV400 Sunglasses',           3, 'Protects eyes from bright sunlight',               135000.00, 100),
    ('Digital Sports Watch',       3, 'Water resistant up to 50m, stopwatch feature',     275000.00,  45),
    ('Leather Belt',               3, 'Genuine cowhide leather, casual buckle',           180000.00,  75);

INSERT INTO orders (user_id, total_price, status)
VALUES
    (1, 905000.00, 'COMPLETED'),  -- Nike Air Max Running Shoes + Sports Socks 3-Pack
    (2, 195000.00, 'PENDING'),    -- Plain Cotton Combed T-Shirt + Unisex Baseball Cap
    (3, 375000.00, 'PROCESSING'), -- Fleece Jogger Pants + Leather Belt
    (4, 450000.00, 'COMPLETED'),  -- Windbreaker Jacket
    (5, 455000.00, 'SHIPPED'),    -- Waterproof Backpack + UV400 Sunglasses
    (6, 395000.00, 'COMPLETED'),  -- Digital Sports Watch + Unisex Baseball Cap
    (7, 205000.00, 'PENDING'),    -- 2x Plain Cotton Combed T-Shirt + Sports Socks 3-Pack
    (8, 850000.00, 'COMPLETED'),  -- Nike Air Max Running Shoes
    (9, 645000.00, 'CANCELLED'),  -- Fleece Jogger Pants + Windbreaker Jacket
    (10, 315000.00, 'SHIPPED'),   -- Leather Belt + UV400 Sunglasses
    (1, 195000.00, 'PROCESSING'), -- T-Shirt + Cap
    (1, 320000.00, 'SHIPPED'),    -- Backpack
    (2, 305000.00, 'COMPLETED'),  -- Jogger Pants + 2x Socks
    (2, 315000.00, 'CANCELLED'),  -- Sunglasses + Belt
    (3, 850000.00, 'PENDING'),    -- Running Shoes
    (3, 425000.00, 'COMPLETED'),  -- 2x T-Shirt + Watch
    (4, 375000.00, 'SHIPPED'),    -- Backpack + Socks
    (4, 255000.00, 'PROCESSING'), -- Cap + Sunglasses
    (5, 390000.00, 'COMPLETED'),  -- 2x Jogger Pants
    (5, 630000.00, 'PENDING'),    -- Jacket + Belt
    (6, 970000.00, 'SHIPPED'),    -- Running Shoes + Cap
    (6, 240000.00, 'COMPLETED'),  -- T-Shirt + 3x Socks
    (7, 455000.00, 'PENDING'),    -- Backpack + Sunglasses
    (7, 455000.00, 'PROCESSING'), -- Watch + Belt
    (8, 315000.00, 'COMPLETED'),  -- Jogger Pants + Cap
    (8, 225000.00, 'CANCELLED'),  -- 3x T-Shirt
    (9, 505000.00, 'SHIPPED'),    -- Jacket + Socks
    (9, 985000.00, 'COMPLETED'),  -- Running Shoes + Sunglasses
    (10, 595000.00, 'PENDING'),   -- Backpack + Watch
    (10, 420000.00, 'PROCESSING');-- 2x Cap + Belt

INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT
    order_data.order_id,
    order_data.product_id,
    order_data.quantity,
    products.price AS unit_price
FROM (
    VALUES
        (1, 1, 1), (1, 6, 1),
        (2, 2, 1), (2, 4, 1),
        (3, 3, 1), (3, 10, 1),
        (4, 5, 1),
        (5, 7, 1), (5, 8, 1),
        (6, 9, 1), (6, 4, 1),
        (7, 2, 2), (7, 6, 1),
        (8, 1, 1),
        (9, 3, 1), (9, 5, 1),
        (10, 10, 1), (10, 8, 1),
        (11, 2, 1), (11, 4, 1),
        (12, 7, 1),
        (13, 3, 1), (13, 6, 2),
        (14, 8, 1), (14, 10, 1),
        (15, 1, 1),
        (16, 2, 2), (16, 9, 1),
        (17, 7, 1), (17, 6, 1),
        (18, 4, 1), (18, 8, 1),
        (19, 3, 2),
        (20, 5, 1), (20, 10, 1),
        (21, 1, 1), (21, 4, 1),
        (22, 2, 1), (22, 6, 3),
        (23, 7, 1), (23, 8, 1),
        (24, 9, 1), (24, 10, 1),
        (25, 3, 1), (25, 4, 1),
        (26, 2, 3),
        (27, 5, 1), (27, 6, 1),
        (28, 1, 1), (28, 8, 1),
        (29, 7, 1), (29, 9, 1),
        (30, 4, 2), (30, 10, 1)
) AS order_data(order_id, product_id, quantity)
JOIN products ON products.id = order_data.product_id;
