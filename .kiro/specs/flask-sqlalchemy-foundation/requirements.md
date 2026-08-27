# Requirements Document

## Introduction

RevoShop's database was designed and validated in Checkpoint 1. This checkpoint adds the application layer: a Flask app connected to the existing `revoshop_db` PostgreSQL database through SQLAlchemy, with every Checkpoint 1 table represented as a model, a Flask-Migrate history that includes adding a `role` column to users, and database-backed user registration and retrieval routes.

Scope is deliberately narrow. Hardcoded product routes serve as a warm-up, and only the User module gets database-backed routes. Full CRUD for products, categories, orders, and auth is out of scope and belongs to Checkpoint 3. Deployment is also out of scope; everything runs locally.

The critical constraint is that `revoshop_db` already exists and is populated with 10 users, 4 categories, 10 products, 30 orders, and 54 order items. The application layer must adopt that database as-is rather than recreating it, and every migration must preserve the existing rows.

## Glossary

- **Association table**: A table that links two other tables to express a many-to-many relationship. Here, `order_items` links `orders` and `products`.
- **Autogenerate**: Flask-Migrate's comparison of the models against the live database to produce a migration file automatically.
- **Baseline / stamp**: Recording a migration revision as already applied, without running its operations, so an existing database is recognized as being at that revision.
- **Checkpoint 1 schema**: The five tables defined in `schema.sql`: `users`, `categories`, `products`, `orders`, and `order_items`.
- **Downgrade**: The reverse operation of a migration, undoing its schema change.
- **Migration**: A version-controlled, reviewable file describing a schema change, applied through Flask-Migrate.
- **Model**: A Python class mapping to a database table through SQLAlchemy.
- **Revision**: A single identified entry in the migration history.
- **Seeded data**: The Checkpoint 1 sample rows already present in `revoshop_db`: 10 users, 4 categories, 10 products, 30 orders, and 54 order items.
- **`revoshop_db`**: The existing PostgreSQL database created and populated during Checkpoint 1.

## Requirements

### Requirement 1: Hardcoded Product Endpoints

**User Story:** As a developer warming up with Flask, I want product routes that return hardcoded JSON, so that I can confirm routing and JSON serialization work before involving the database.

#### Acceptance Criteria

1. WHEN a GET request is made to `/products` THEN the system SHALL return the complete hardcoded product list as a JSON response produced by `jsonify()`
2. WHEN a GET request is made to `/products/<id>` with an id present in the hardcoded list THEN the system SHALL return only the matching product as JSON
3. WHEN a GET request is made to `/products/<id>` with an id absent from the hardcoded list THEN the system SHALL return a JSON error body with HTTP status 404
4. THE hardcoded product data SHALL be structured as a list of dictionaries where every entry uses the same keys, including at minimum `id`, `name`, and `price`
5. THE hardcoded product routes SHALL NOT query the database

### Requirement 2: Flask Application and Database Connection

**User Story:** As a developer, I want the Flask app configured to connect to `revoshop_db` through SQLAlchemy, so that models and routes operate against the real Checkpoint 1 database.

#### Acceptance Criteria

1. THE application SHALL set `SQLALCHEMY_DATABASE_URI` using a PostgreSQL connection string in the form `postgresql://user:password@host/dbname`
2. THE configured target database SHALL be `revoshop_db`
3. THE application SHALL initialize a SQLAlchemy database instance bound to the Flask app
4. WHEN the application starts THEN it SHALL start without connection or configuration errors
5. THE application SHALL provide a way to verify the live connection succeeds against the running PostgreSQL server
6. THE configuration module SHALL define the PostgreSQL connection string for the local development `revoshop_db` database as a literal value in the source file, as a deliberate local-only simplification for this checkpoint
7. WHERE `SQLALCHEMY_TRACK_MODIFICATIONS` is concerned THE application SHALL disable it to avoid the Flask-SQLAlchemy overhead warning
8. THE configuration module SHALL read `SECRET_KEY` from the environment, and IF the `SECRET_KEY` environment variable is absent THEN THE configuration module SHALL apply a documented development fallback value

### Requirement 3: Models Mirroring the Checkpoint 1 Schema

**User Story:** As a developer, I want SQLAlchemy models that mirror the Checkpoint 1 tables exactly, so that the ORM layer and the existing database agree and no unintended migration is generated.

#### Acceptance Criteria

1. THE system SHALL define a `User` model containing `id`, `username`, `email`, `password_hash`, `is_active`, and `created_at`
2. THE `User` model SHALL mark `email` as unique
3. THE `User` model SHALL mark `username` as unique
4. THE `User` model `created_at` field SHALL default to the current timestamp
5. THE system SHALL define a `Category` model containing `id`, `name`, and `description`, with `name` unique
6. THE system SHALL define a `Product` model containing `id`, `category_id`, `name`, `description`, `price`, `stock_quantity`, and `created_at`
7. THE system SHALL define an `Order` model containing `id`, `user_id`, `total_price`, `status`, and `created_at`
8. THE `Product` model SHALL declare a foreign key to `categories.id` and THE `Order` model SHALL declare a foreign key to `users.id`
9. THE models SHALL use column types, nullability, defaults, and numeric precision that match the Checkpoint 1 table definitions
10. THE models SHALL preserve the Checkpoint 1 table names `users`, `categories`, `products`, and `orders`
11. THE `User` model SHALL NOT define a `role` column in its initial state, because `role` is introduced later through a migration
12. WHEN an autogenerate check is run against the untouched Checkpoint 1 database THEN the models SHALL produce no unintended schema differences

### Requirement 4: order_items Association Table

**User Story:** As a developer, I want `order_items` defined as an association table so that the many-to-many relationship between orders and products is expressed through the ORM.

#### Acceptance Criteria

1. THE system SHALL define `order_items` using `db.Table()` rather than as a model class
2. THE association table SHALL define a foreign key column referencing `orders.id`
3. THE association table SHALL define a foreign key column referencing `products.id`
4. THE association table SHALL retain the Checkpoint 1 `quantity` and `unit_price` columns
5. THE association table SHALL keep `(order_id, product_id)` as its composite primary key
6. THE `Order` model SHALL expose a relationship to products through the association table
7. THE `Product` model SHALL expose the reverse relationship to orders
8. THE association table definition SHALL match the existing `order_items` table so that no migration is generated for it

### Requirement 5: User Registration Route

**User Story:** As an API client, I want to register a user through an endpoint, so that new accounts are persisted to the database.

#### Acceptance Criteria

1. WHEN a POST request is made to the register route with valid `username`, `email`, and password input THEN the system SHALL create a new `User` instance, persist it with `db.session.add()` and `db.session.commit()`, and return the created user as JSON with HTTP status 201
2. THE register route SHALL NOT store the submitted password in plain text
3. THE register route response SHALL NOT include `password_hash`
4. WHEN required fields are missing or empty THEN the system SHALL return a JSON validation error with HTTP status 400 and SHALL NOT persist a user
5. WHEN the submitted `username` or `email` already exists THEN the system SHALL return a JSON conflict error with HTTP status 409 and SHALL NOT persist a duplicate
6. WHEN the request body is absent or is not valid JSON THEN the system SHALL return a JSON error with HTTP status 400
7. IF a database error occurs during the write THEN the system SHALL roll back the session and return a JSON error response

### Requirement 6: User Retrieval Route

**User Story:** As an API client, I want to retrieve a user by id, so that I can confirm registration persisted and read account data back.

#### Acceptance Criteria

1. WHEN a GET request is made to the retrieve route with an id that exists THEN the system SHALL return that user as JSON with HTTP status 200
2. WHEN a GET request is made to the retrieve route with an id that does not exist THEN the system SHALL return a JSON not-found error with HTTP status 404
3. THE retrieve route response SHALL NOT include `password_hash`
4. THE retrieve route response SHALL include `id`, `username`, `email`, and `created_at`
5. WHERE the `role` column exists after its migration THE retrieve route response SHALL include `role`

### Requirement 7: Migration History Baselined on the Existing Database

**User Story:** As a developer, I want a Flask-Migrate history that adopts the already-populated Checkpoint 1 database, so that migrations run cleanly without recreating existing tables or destroying seeded data.

#### Acceptance Criteria

1. THE repository SHALL contain an initialized Flask-Migrate environment with a versions history
2. THE migration history SHALL include an initial revision representing the Checkpoint 1 schema
3. WHEN the initial revision is applied to the existing populated `revoshop_db` THEN the system SHALL NOT attempt to create tables that already exist
4. THE project SHALL document how to mark the existing database as already matching the initial revision so that subsequent migrations start from the correct baseline
5. WHEN migrations are applied THEN all existing rows across all five tables SHALL be preserved
6. THE migration workflow SHALL follow generate, review the generated file, then apply
7. THE project SHALL document the commands used to initialize, generate, and apply migrations

### Requirement 8: Role Column Migration

**User Story:** As a developer, I want the `role` column added to users through a migration, so that the schema change is version-controlled and provably non-destructive.

#### Acceptance Criteria

1. THE `User` model SHALL be updated to include a `role` column
2. THE `role` column SHALL be introduced through a generated Flask-Migrate revision, not by hand-editing the database
3. THE `role` migration SHALL define a default value so that pre-existing user rows receive a valid role rather than being left invalid
4. WHEN the `role` migration is applied THEN all 10 existing users SHALL remain present with their original `id`, `username`, `email`, and `created_at` values unchanged
5. THE `role` migration SHALL provide a working downgrade path that removes the column
6. THE `role` column SHALL be verifiable in a database client as part of the `users` table structure

### Requirement 9: Many-to-Many Sample Data

**User Story:** As a reviewer, I want sample data linking an order to multiple products through the association table, so that the many-to-many relationship is demonstrably working.

#### Acceptance Criteria

1. THE system SHALL provide a repeatable way to insert sample data that links at least one order to multiple products through the `order_items` association table
2. THE sample data SHALL be insertable through the SQLAlchemy layer so that the relationship is exercised through the ORM
3. WHEN the linked order is loaded through the ORM THEN its products relationship SHALL return more than one product
4. THE sample data routine SHALL populate `quantity` and `unit_price` for every association row it creates
5. THE sample data routine SHALL be safe to run against the already-seeded database without violating the composite primary key
6. THE resulting association rows SHALL be verifiable in a database client

### Requirement 10: Project Structure and Dependencies

**User Story:** As a reviewer, I want a clean project layout and pinned dependencies, so that the application is understandable and reproducible locally.

#### Acceptance Criteria

1. THE repository SHALL contain a `requirements.txt` listing the Python dependencies with pinned versions
2. THE project SHALL separate models, routes, and configuration into distinct modules
3. THE project SHALL keep the Checkpoint 1 SQL files intact in the same repository
4. THE `.gitignore` SHALL exclude the Python virtual environment, bytecode caches, and local environment files
5. THE `README.md` SHALL document how to create the virtual environment, install dependencies, configure the database connection, run migrations, and start the app
6. THE `README.md` SHALL document the available endpoints and how to exercise them

### Requirement 11: Local Verification Evidence

**User Story:** As a reviewer, I want the checkpoint's behavior to be verifiable locally, so that the required demo evidence can be captured.

#### Acceptance Criteria

1. THE application SHALL run locally so that `GET /products` and `GET /products/<id>` can be exercised in an API client
2. THE application SHALL run locally so that user registration, successful retrieval, and the not-found retrieval case can be exercised in an API client
3. THE `README.md` SHALL provide example requests and expected responses for each documented endpoint
4. THE project SHALL provide database verification queries or documented steps confirming the `role` column and the `order_items` many-to-many links

## Out of Scope

- Full CRUD for products, categories, orders, and authentication, which belongs to Checkpoint 3
- Login, sessions, tokens, or role-based authorization enforcement
- Deployment, hosting, and production configuration
- Capturing the Postman and pgAdmin screenshots and committing them, which the user handles manually
- The ERD diagram and Git commit history curation, which the user handles manually
