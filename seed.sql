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
    (1, 905000.00, 'COMPLETED'), -- Sepatu Lari (850k) + Kaus Kaki (55k)
    (2, 195000.00, 'PENDING'),   -- Kaus Polos (75k) + Topi Baseball (120k)
    (3, 375000.00, 'PROCESSING'),-- Celana Jogger (195k) + Ikat Pinggang (180k)
    (4, 450000.00, 'COMPLETED'), -- Jaket Windbreaker (450k)
    (5, 455000.00, 'SHIPPED'),    -- Tas Ransel (320k) + Kacamata Hitam (135k)
    (6, 395000.00, 'COMPLETED'), -- Jam Tangan (275k) + Topi Baseball (120k)
    (7, 205000.00, 'PENDING'),   -- 2x Kaus Polos (150k) + Kaus Kaki (55k)
    (8, 850000.00, 'COMPLETED'), -- Sepatu Lari (850k)
    (9, 645000.00, 'CANCELLED'), -- Celana Jogger (195k) + Jaket Windbreaker (450k)
    (10, 315000.00, 'SHIPPED');  -- Ikat Pinggang (180k) + Kacamata Hitam (135k)

INSERT INTO order_items (order_id, product_id, quantity)
VALUES
    -- Order 1 (Total: 905k)
    (1, 1, 1), -- 1x Sepatu Lari Nike (850k)
    (1, 6, 1), -- 1x Kaus Kaki Olahraga (55k)

    -- Order 2 (Total: 195k)
    (2, 2, 1), -- 1x Kaus Polos (75k)
    (2, 4, 1), -- 1x Topi Baseball (120k)

    -- Order 3 (Total: 375k)
    (3, 3, 1), -- 1x Celana Jogger (195k)
    (3, 10, 1),-- 1x Ikat Pinggang Kulit (180k)

    -- Order 4 (Total: 450k)
    (4, 5, 1), -- 1x Jaket Windbreaker (450k)

    -- Order 5 (Total: 455k)
    (5, 7, 1), -- 1x Tas Ransel (320k)
    (5, 8, 1), -- 1x Kacamata Hitam (135k)

    -- Order 6 (Total: 395k)
    (6, 9, 1), -- 1x Jam Tangan Digital (275k)
    (6, 4, 1), -- 1x Topi Baseball (120k)

    -- Order 7 (Total: 205k)
    (7, 2, 2), -- 2x Kaus Polos (150k)
    (7, 6, 1), -- 1x Kaus Kaki Olahraga (55k)

    -- Order 8 (Total: 850k)
    (8, 1, 1), -- 1x Sepatu Lari Nike (850k)

    -- Order 9 (Total: 645k)
    (9, 3, 1), -- 1x Celana Jogger (195k)
    (9, 5, 1), -- 1x Jaket Windbreaker (450k)

    -- Order 10 (Total: 315k)
    (10, 10, 1),-- 1x Ikat Pinggang Kulit (180k)
    (10, 8, 1); -- 1x Kacamata Hitam (135k)
    