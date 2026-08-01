# RevoShop Database Setup

This repository contains SQL scripts to build and populate the RevoShop e-commerce database locally using PostgreSQL and DBeaver.

## Prerequisites
- PostgreSQL (Version 14 or higher)
- DBeaver Universal Database Tool

## Local Installation Steps

1. **Create a New Database:**
   Open your PostgreSQL server connection in DBeaver and execute the following command:
   ```sql
   CREATE DATABASE revoshop_db;
   ```

2. **Execute the Database Schema:**
   Switch your SQL Editor connection connection target to `revoshop_db`. Run the `schema.sql` file to generate the required tables:
   - `users`
   - `categories`
   - `products`
   - `orders`
   - `order_items`

3. **Seed Database Sample Data:**
   Run the `seed.sql` file to populate each table with 10 rows of realistic sample transaction data.

4. **Run Analytical Queries**
   You can verify the database setup and extract metrics by running the queries provided in the query file `queries.sql`.

## Database Relationship Overview
- The `products` table links to `categories` via the `category_id` foreign key.
- The `order_items` table serves as a junction table connecting `orders` and `products` to handle multi-item shopping carts seamlessly.

## Author
* **Name:** Muhammad Alzed Mukarom
* **GitHub Username:** @alzedmkrom