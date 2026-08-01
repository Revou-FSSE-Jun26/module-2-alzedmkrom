CREATE DATABASE revoshop_db;

CREATE TABLE users (
    id            SERIAL primary key, -- YOUR DECISION: primary key, auto-increment
    username      VARCHAR(200) unique not null, -- YOUR DECISION: short text, required
    email         VARCHAR(50) unique not null, -- YOUR DECISION: text, required, max 255 chars
    password_hash VARCHAR(255) not null, -- YOUR DECISION: text, required (stores hashed password)
    is_active     BOOLEAN default TRUE, -- YOUR DECISION: true/false flag, optional
    created_at    TIMESTAMP default NOW() -- YOUR DECISION: date + time, optional (auto-set)
);

CREATE TABLE categories (
    id 			SERIAL PRIMARY KEY,
    name 		VARCHAR(100) unique NOT NULL,
    description TEXT
);

CREATE TABLE products (
    id             SERIAL primary key, -- YOUR DECISION: primary key, auto-increment
    category_id	   INTEGER not null,
    name           VARCHAR(200) not null, -- YOUR DECISION: short text, required
    description    TEXT, -- YOUR DECISION: long text, optional
    price          NUMERIC(11, 2) not null, -- YOUR DECISION: exact decimal, required
    stock_quantity INTEGER not null, -- YOUR DECISION: whole number, required
    created_at     TIMESTAMP default NOW(), -- YOUR DECISION: date + time, optional (auto-set)
    constraint fk_products_category foreign key (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);

CREATE TABLE orders (
    id           SERIAL primary key, -- YOUR DECISION: primary key, auto-increment
    user_id      INTEGER unique not null, -- YOUR DECISION: whole number (references a user), required
    total_price NUMERIC(14 , 2) check (total_price >= 0) not null, -- YOUR DECISION: exact decimal, required
    status       VARCHAR(25) default 'Pending' not null, -- YOUR DECISION: short text (e.g. 'pending', 'shipped'), required
    created_at   TIMESTAMP default NOW(), -- YOUR DECISION: date + time, optional (auto-set)
    constraint fk_orders_user foreign key (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE order_items (
    order_id INTEGER not null,
    product_id INTEGER not NULL,
    quantity INTEGER not null check (quantity > 0),
    PRIMARY KEY (order_id, product_id),
    CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE, 
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

