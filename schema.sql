CREATE DATABASE revoshop_db;

CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(255) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Enforce case-insensitive uniqueness for usernames and email addresses.
CREATE UNIQUE INDEX uq_users_username_ci ON users (LOWER(username));
CREATE UNIQUE INDEX uq_users_email_ci ON users (LOWER(email));

CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE products (
    id             SERIAL PRIMARY KEY,
    category_id    INTEGER NOT NULL,
    name           VARCHAR(255) NOT NULL,
    description    TEXT,
    price          NUMERIC(11, 2) NOT NULL CHECK (price >= 0),
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_products_category
        FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);

CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    total_price NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (total_price >= 0),
    status      VARCHAR(75) NOT NULL DEFAULT 'PENDING',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(14, 2) NOT NULL CHECK (unit_price >= 0),
    PRIMARY KEY (order_id, product_id),
    CONSTRAINT fk_items_order
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_items_product
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

-- PostgreSQL does not automatically index foreign-key columns.
-- order_items.order_id is already covered by the composite primary key.
CREATE INDEX idx_products_category_id ON products (category_id);
CREATE INDEX idx_orders_user_id ON orders (user_id);
CREATE INDEX idx_order_items_product_id ON order_items (product_id);

SELECT setval('users_id_seq', 20, true);
SELECT setval('categories_id_seq', 4, true);
SELECT setval('products_id_seq', 10, true);
SELECT setval('orders_id_seq', 30, true);
SELECT setval('order_items_id_seq', 20, true);

