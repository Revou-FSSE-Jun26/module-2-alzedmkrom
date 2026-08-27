# Implementation Plan: Flask + SQLAlchemy Foundation

## Overview

Build the Flask application layer over the already-populated `revoshop_db` in the order the import graph allows: configuration, then app and extensions, then the hardcoded warm-up routes, then models mirroring `schema.sql`, then the baselined migration history, then the database-backed user routes, and finally the many-to-many demonstration and documentation.

Implementation language is Python, using Flask, Flask-SQLAlchemy, and Flask-Migrate exactly as specified in the design. Every task writes real files at the repository root per the flat layout in the design; the Checkpoint 1 SQL files stay untouched.

Property tests use `pytest` plus `hypothesis`. They are all optional sub-tasks (`*`) because automated tests are not a deliverable for this checkpoint, but each one encodes a correctness property from the design and can be run to replace a manual verification step.

## Tasks

- [x] 1. Project setup and configuration
  - [x] 1.1 Create dependency and environment files
    - Create `requirements.txt` pinning the resolved versions of `Flask`, `Flask-SQLAlchemy`, `Flask-Migrate`, `SQLAlchemy`, `alembic`, `psycopg2-binary`, and `python-dotenv`
    - Create `.flaskenv` with `FLASK_APP=app.py` and `FLASK_DEBUG=1`
    - Create `.env.example` documenting `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, and `SECRET_KEY` with no real credentials
    - Extend `.gitignore` to exclude the virtual environment, `__pycache__`, and `.env`
    - _Requirements: 10.1, 10.4, 2.6_

  - [x] 1.2 Implement `config.py`
    - Define a `Config` class that imports nothing from the project
    - Assemble `SQLALCHEMY_DATABASE_URI` as `postgresql://user:password@host/dbname`, letting `DATABASE_URL` win when set and otherwise building from the discrete variables with local defaults targeting `revoshop_db`
    - Pass the password through `urllib.parse.quote_plus` before embedding it
    - Set `SQLALCHEMY_TRACK_MODIFICATIONS = False` and read `SECRET_KEY` with a development fallback
    - _Requirements: 2.1, 2.2, 2.6, 2.7_

- [x] 2. Application core, error handling, and hardcoded product routes
  - [x] 2.1 Implement `extensions.py`
    - Create the module-level `app = Flask(__name__)` and load `Config` with `app.config.from_object`
    - Create `db = SQLAlchemy(app)` and `migrate = Migrate(app, db)` in the direct bound form
    - _Requirements: 2.3, 2.4_

  - [x] 2.2 Implement `errors.py` JSON error handlers
    - Register handlers for 400, 404, 405, and 500 on the imported `app`
    - Return the consistent `{ "error": ..., "message": ... }` envelope so no HTML error page ever reaches an API client
    - Log database failure details server-side instead of returning them
    - _Requirements: 1.3, 5.6, 6.2, 5.7_

  - [x] 2.3 Implement the hardcoded product routes in `routes.py`
    - Define `products_bp = Blueprint("products", __name__)` importing only `db` and models, never `app`
    - Define the module-level hardcoded product list as dictionaries with identical `id`, `name`, `category`, `price`, `stock_quantity` keys, mirroring real Checkpoint 1 products from `seed.sql`
    - Implement `GET /products` returning the full list via `jsonify()` and `GET /products/<int:product_id>` returning one product or a 404 JSON error
    - Issue no SQL from either route
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.4 Create the `app.py` entry point
    - Import `app` from `extensions`, import `products_bp` from `routes`, and import `models`, `errors`, and `cli` for their registration side effects with `# noqa: F401`
    - Register the blueprints explicitly and run the development server under `if __name__ == "__main__"` with `debug=True`
    - Leave the `users_bp` registration line ready to add when task 10 lands
    - _Requirements: 2.4, 10.2_

  - [ ]* 2.5 Set up the test scaffolding
    - Add `pytest` and `hypothesis` to a `requirements-dev.txt`
    - Create `tests/conftest.py` with a Flask test client fixture and a session fixture that rolls back after each test so `revoshop_db` rows are never mutated by a test run
    - _Requirements: 2.3_

  - [ ]* 2.6 Write property test for hardcoded route isolation
    - **Property 11: Hardcoded route isolation**
    - **Validates: Requirements 1.5**
    - Assert the product routes emit zero SQL statements, for example by attaching an engine event listener or pointing the URI at an unreachable host

  - [ ]* 2.7 Write unit tests for the product routes
    - Test `GET /products` returns 200 with every entry carrying the same keys
    - Test a known id returns 200 with one product and an unknown id returns a 404 JSON body
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Checkpoint - app boots and product endpoints respond
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Models mirroring the Checkpoint 1 schema
  - [x] 4.1 Implement `models.py` with the four models and the association table
    - Define `order_items` with `db.Table()` before `Order` and `Product`, keeping the composite primary key, `quantity`, `unit_price`, the named check constraints, and the `CASCADE`/`RESTRICT` foreign keys from `schema.sql`
    - Define `User`, `Category`, `Product`, and `Order` with the exact column types, nullability, defaults, and numeric precision in the design's data model table, preserving the Checkpoint 1 table names
    - Declare the named check constraints and the two `LOWER()` functional unique indexes in `__table_args__`
    - Relate `Order.products` and `Product.orders` through `secondary=order_items` with `back_populates` and `viewonly=True`
    - Omit any `role` column on `User` at this stage
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 4.2 Add password hashing and `to_dict()` serializers
    - Implement `User.set_password` and `User.check_password` using Werkzeug hashing
    - Implement `to_dict()` on each model, with `User.to_dict()` omitting `password_hash` and emitting `created_at` as an ISO 8601 string
    - _Requirements: 5.2, 5.3, 6.3, 6.4_

  - [ ]* 4.3 Write property test for no plaintext at rest
    - **Property 5: No plaintext at rest**
    - **Validates: Requirements 5.2**
    - Generate candidate passwords with Hypothesis, hash them through `set_password`, and assert the raw value appears in no column of the resulting row while `check_password` still verifies it

  - [ ]* 4.4 Write unit tests for the models
    - Test that column types, nullability, and numeric precision match `schema.sql`
    - Test that the `order_items` primary key is `(order_id, product_id)` and its check constraints reject `quantity <= 0` and negative `unit_price`
    - _Requirements: 3.9, 4.4, 4.5_

- [x] 5. Connection verification command
  - [x] 5.1 Implement `flask check-db` in `cli.py`
    - Execute `SELECT version()` through the engine and print the server version plus the resolved target database
    - Print the row count of `users`, `categories`, `products`, `orders`, and `order_items`
    - _Requirements: 2.5, 2.4_

- [x] 6. Migration environment and Checkpoint 1 baseline
  - [x] 6.1 Initialize Flask-Migrate and generate the reviewed baseline revision
    - Run `flask db init`, then `flask db migrate` to autogenerate revision 1
    - Review the generated file by hand against `schema.sql` so it describes the five tables, the two case-insensitive unique indexes, and the three foreign-key indexes and nothing else
    - _Requirements: 7.1, 7.2, 7.6, 7.7_

  - [x] 6.2 Baseline the populated database by stamping
    - Run `flask db stamp <revision-1>` so `alembic_version` records the revision without executing DDL against the existing tables
    - Confirm with `flask check-db` that the counts are still 10, 4, 10, 30, and 54
    - _Requirements: 7.3, 7.4, 7.5_

  - [ ]* 6.3 Write property test for model and database parity
    - **Property 1: Model and database parity**
    - **Validates: Requirements 3.9, 3.10, 3.12, 4.8**
    - Run Alembic autogenerate programmatically against the live database and assert the produced migration script contains no operations

- [x] 7. Unique constraint revision
  - [x] 7.1 Generate, review, and apply the `users` unique constraint revision
    - Generate revision 2 for the `unique=True` declarations on `username` and `email`, review the generated operations, then `flask db upgrade`
    - Confirm the existing 10 users build the constraints cleanly and the functional `LOWER()` indexes remain in place
    - _Requirements: 3.2, 3.3, 7.5, 7.6_

  - [ ]* 7.2 Write property test for seed preservation across migrations
    - **Property 2: Seed preservation across migrations**
    - **Validates: Requirements 7.5, 8.4**
    - Snapshot `id`, `username`, `email`, and `created_at` for all users plus the five table counts, apply the migrations, and assert every value is unchanged

- [x] 8. Role column migration
  - [x] 8.1 Add `role` to `User` and generate the reviewed revision
    - Add `role` as `String(50), nullable=False, server_default=text("'CUSTOMER'")` to the model
    - Generate revision 3, review that the `add_column` carries the server default so PostgreSQL backfills existing rows in one statement, and confirm `downgrade()` drops the column
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

  - [x] 8.2 Apply the revision and expose `role` in responses
    - Run `flask db upgrade` and verify all 10 users keep their original `id`, `username`, `email`, and `created_at`
    - Include `role` in `User.to_dict()`
    - _Requirements: 8.4, 8.6, 6.5_

  - [ ]* 8.3 Write property test for role backfill totality
    - **Property 3: Role backfill totality**
    - **Validates: Requirements 8.3, 8.4**
    - Assert no `users` row has a null `role` after the revision, including rows inserted without an explicit role

- [x] 9. Checkpoint - migrations applied with seeded data intact
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Database-backed user routes
  - [x] 10.1 Implement the registration route
    - Add `users_bp = Blueprint("users", __name__, url_prefix="/users")` to `routes.py` and register it in `app.py`
    - Implement `POST /users/register` following the design's validation sequence: `request.get_json(silent=True)` for a 400 on a missing or malformed body, 400 naming any missing or blank `username`, `email`, or `password`, and a case-insensitive duplicate pre-check returning 409
    - Build the `User`, call `set_password`, persist with `db.session.add()` and `db.session.commit()`, and return 201 with `to_dict()`
    - Wrap the write in `try/except`, rolling back and returning 409 on `IntegrityError` and 500 on any other `SQLAlchemyError`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 10.2 Implement the retrieval route
    - Implement `GET /users/<int:user_id>` using `db.session.get(User, user_id)`, returning 200 with `to_dict()` or a 404 JSON error naming the id
    - Confirm the payload carries `id`, `username`, `email`, `created_at`, and `role` and never `password_hash`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 10.3 Write property test for hash secrecy
    - **Property 4: Hash secrecy**
    - **Validates: Requirements 5.3, 6.3**
    - Generate registration payloads with Hypothesis and assert `password_hash` appears in no response body from register or retrieve, including error responses

  - [ ]* 10.4 Write property test for registration atomicity
    - **Property 6: Registration atomicity**
    - **Validates: Requirements 5.4, 5.5, 5.6, 5.7**
    - Generate invalid, duplicate, and malformed-body requests and assert the user count is unchanged, no partial row exists, and a following valid request still succeeds on the same session

  - [ ]* 10.5 Write unit tests for the user routes
    - Test the 201 happy path, the 400 cases for missing fields and a non-JSON body, the 409 duplicate case, and the 200 and 404 retrieval cases
    - _Requirements: 5.1, 5.4, 5.5, 5.6, 6.1, 6.2_

- [x] 11. Many-to-many sample data command
  - [x] 11.1 Implement `flask link-order-products` inserts
    - Extend order 4 with two additional products so it links three products through `order_items`
    - Read each `unit_price` from the product's current price through the ORM and set `quantity` on every inserted row
    - Insert with the PostgreSQL dialect's `on_conflict_do_nothing` against the composite primary key so repeat runs are safe
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

  - [x] 11.2 Recompute the order total and print the relationship
    - Recompute order 4's `total_price` as the sum of `quantity * unit_price` over its association rows and commit
    - Reload the order through the ORM and print `order.products` to show multiple products
    - _Requirements: 9.1, 9.3, 9.6_

  - [ ]* 11.3 Write property test for sample data idempotence
    - **Property 9: Sample data idempotence**
    - **Validates: Requirements 9.5**
    - Invoke the command a generated number of times and assert the association rows and order totals match the single-run result

  - [ ]* 11.4 Write property test for order total consistency
    - **Property 8: Order total consistency**
    - **Validates: Requirements 9.1, 9.6**
    - Assert each touched order's stored `total_price` equals the sum of `quantity * unit_price` over its rows, mirroring the `queries.sql` stored-versus-calculated check returning no rows

  - [ ]* 11.5 Write property test for association payload completeness
    - **Property 7: Association payload completeness**
    - **Validates: Requirements 4.4, 9.4**
    - Assert every `order_items` row has non-null `quantity` and `unit_price` with `quantity > 0` and `unit_price >= 0`

  - [ ]* 11.6 Write property test for many-to-many demonstrability
    - **Property 10: Many-to-many demonstrability**
    - **Validates: Requirements 4.6, 4.7, 9.2, 9.3**
    - Load orders through the ORM and assert at least one returns more than one product from its products relationship, and that the reverse `Product.orders` relationship resolves

- [x] 12. Documentation and verification queries
  - [x] 12.1 Write the `README.md` setup and endpoint documentation
    - Document virtual environment creation, `pip install -r requirements.txt`, connection configuration through `.env`, and both launch paths (`python app.py` and `flask run`)
    - Document the migration commands for init, migrate, review, upgrade, and the `stamp` baseline path for an existing populated database alongside the `upgrade`-from-empty path
    - Document every endpoint with an example request and expected response, plus `flask check-db` and `flask link-order-products`
    - _Requirements: 10.5, 10.6, 7.4, 7.7, 11.1, 11.2, 11.3_

  - [x] 12.2 Add the database verification queries
    - Create a new verification SQL file, leaving `schema.sql`, `seed.sql`, and `queries.sql` unchanged
    - Include queries confirming the `users.role` column and its values, the order 4 association rows, and a re-run of the `queries.sql` integrity checks that must return no rows
    - _Requirements: 11.4, 10.3, 8.6, 9.6_

- [x] 13. Final checkpoint - full verification pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP; the design's stated verification path for this checkpoint is manual and command-driven
- Property tests read and roll back rather than mutate, so they can run against `revoshop_db` without disturbing the seeded rows; point them at a scratch database if you prefer full isolation
- Tasks 6.2 and 7.1 touch the live populated database, so review each generated migration file before applying it
- Checkpoints exist at tasks 3, 9, and 13 for incremental validation

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "4.1"] },
    { "id": 3, "tasks": ["2.4", "4.2", "5.1"] },
    { "id": 4, "tasks": ["2.5", "6.1"] },
    { "id": 5, "tasks": ["2.6", "2.7", "4.3", "4.4", "6.2"] },
    { "id": 6, "tasks": ["6.3", "7.1"] },
    { "id": 7, "tasks": ["7.2", "8.1"] },
    { "id": 8, "tasks": ["8.2"] },
    { "id": 9, "tasks": ["8.3", "10.1"] },
    { "id": 10, "tasks": ["10.2", "11.1"] },
    { "id": 11, "tasks": ["10.3", "10.4", "10.5", "11.2"] },
    { "id": 12, "tasks": ["11.3", "11.4", "11.5", "11.6", "12.1", "12.2"] }
  ]
}
```
