# Design Document

## Overview

This design adds a Flask application layer on top of the existing, already-populated `revoshop_db` PostgreSQL database from Checkpoint 1. The application is a single module-level Flask app using Flask-SQLAlchemy for the ORM and Flask-Migrate for version-controlled schema changes.

The guiding constraint is that the database is the source of truth for the current schema. `revoshop_db` already holds 10 users, 4 categories, 10 products, 30 orders, and 54 order items. The models are therefore written to mirror `schema.sql` exactly, the migration history is baselined against that reality by stamping rather than re-creating, and every subsequent schema change moves forward from that baseline through a reviewed migration.

Two route groups are delivered: hardcoded product endpoints that never touch the database, and database-backed user registration and retrieval. Two Flask CLI commands support verification: one to prove the connection is live, and one to insert the many-to-many demonstration data.

## Architecture

```mermaid
graph TD
    Client[API Client / Postman]

    Entry["app.py<br/>entry point"]
    Config[config.py<br/>Config]
    Ext["extensions.py<br/>app,<br/>db = SQLAlchemy(app), migrate"]
    Models["models.py<br/>User, Category, Product, Order,<br/>order_items db.Table"]
    Routes["routes.py<br/>products_bp: hardcoded<br/>users_bp: register + retrieve"]
    Errors[errors.py<br/>JSON error handlers]
    CLI[cli.py<br/>check-db, link-order-products]

    Migrations[migrations/versions<br/>baseline, unique, role]
    DB[(revoshop_db<br/>PostgreSQL)]

    Client -->|GET /products| Routes
    Client -->|POST /users/register| Routes
    Client -->|GET /users/id| Routes

    Config --> Ext
    Ext --> Models
    Ext --> Errors
    Ext --> CLI
    Routes --> Models
    CLI --> Models
    Entry --> Ext
    Entry --> Models
    Entry -->|register_blueprint| Routes
    Entry --> Errors
    Entry --> CLI
    Models --> DB
    Migrations -->|alembic_version| DB
```

Modules import `app` and `db` from `extensions.py` and nothing imports back into it, so the import graph stays acyclic with no deferred or bottom-of-file imports needed. `routes.py` is the exception that needs only `db`, because its blueprints are defined without an app.

### Request flow

Hardcoded product requests are served entirely from an in-module Python list, satisfying Requirement 1.5. Database-backed user requests flow through the route layer, into the `User` model, through the shared `db.session`, and out to PostgreSQL. All error responses are JSON, including framework-generated 404s and 405s, so an API client never receives an HTML error page.

## Project Structure

A flat layout of single-purpose modules at the repository root. No packages, so no `__init__.py` anywhere.

```
module-2-alzedmkrom/
├── config.py                 # Config: literal SQLALCHEMY_DATABASE_URI, SECRET_KEY
├── extensions.py             # app, db = SQLAlchemy(app), migrate
├── models.py                 # User, Category, Product, Order, order_items
├── routes.py                 # products_bp + users_bp blueprints
├── errors.py                 # JSON error handlers
├── cli.py                    # check-db, link-order-products
├── app.py                    # entry point, registers blueprints and runs
├── migrations/               # Flask-Migrate environment
│   └── versions/
├── schema.sql                # Checkpoint 1, unchanged
├── seed.sql                  # Checkpoint 1, unchanged
├── queries.sql               # Checkpoint 1, unchanged
├── .env.example              # SECRET_KEY only; the database URI is literal in config.py
├── .flaskenv                 # FLASK_APP for the CLI
├── requirements.txt
├── README.md
└── .gitignore
```

Models, routes, and configuration are separated into distinct modules, satisfying Requirement 10.2. The Checkpoint 1 SQL files stay at the repository root untouched, satisfying Requirement 10.3.

Import direction is strictly one-way:

```
config.py  →  extensions.py  →  models.py  →  routes.py / cli.py / errors.py  →  app.py
```

Nothing imports `app.py`, and nothing imports back into `config.py` or `extensions.py`, which is what keeps the graph acyclic. Per-module imports:

| Module | Imports from the project |
|---|---|
| `config.py` | nothing |
| `extensions.py` | `config` (`Config`) |
| `models.py` | `extensions` (`db`) |
| `routes.py` | `extensions` (`db`), `models` |
| `errors.py` | `extensions` (`app`) |
| `cli.py` | `extensions` (`app`, `db`), `models` |
| `app.py` | `extensions`, `routes`, `models`, `errors`, `cli` |

**Why `Config` gets its own module.** A dedicated configuration module is the conventional Flask layout, and it keeps the door open for `DevConfig` and `TestConfig` subclasses in a later checkpoint without touching app wiring. It is also the safe position in the import graph: `config.py` imports nothing from the project, so it can sit at the head of the chain.

**Why `Config` does not go into `app.py`.** That placement would invert an edge and create a genuine cycle, since `extensions.py` would need `Config` from `app.py` while `app.py` needs the `app` object from `extensions.py`. It happens to survive `flask run` when `Config` is declared above the import line, because the partially-initialized module already carries the attribute being requested. It fails under `python app.py`: the module then executes as `__main__`, the `from app import Config` inside `extensions` re-imports the file under the name `app`, and that second pass reaches `from extensions import app` while `extensions` is still mid-initialization and has no `app` attribute yet. Keeping configuration in a leaf module removes the possibility entirely.

## Components and Interfaces

### Configuration (`config.py`)

Holds the `Config` class and nothing else, importing nothing from the project. It carries three settings:

| Setting | Value | Purpose |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | literal `postgresql://postgres:<password>@localhost/revoshop_db` | Connects to the local `revoshop_db` in the exact `postgresql://user:password@host/dbname` form (Requirements 2.1, 2.2, 2.6) |
| `SQLALCHEMY_TRACK_MODIFICATIONS` | `False` | Disables Flask-SQLAlchemy event tracking and its overhead warning (Requirement 2.7) |
| `SECRET_KEY` | `os.environ.get("SECRET_KEY", "dev-secret-key-change-me")` | Flask signing key, read from the environment with a documented development fallback (Requirement 2.8) |

The connection string is a literal assignment rather than an assembled value. That is a deliberate simplification, and the tradeoff is worth stating plainly: the database password is committed to the repository. That is acceptable here only because this is a local-only checkpoint against a development database with no deployment in scope. A deployed version would move the string out of source control and into an environment variable.

The escape hatch is one line. Replacing the literal with `os.environ.get("DATABASE_URL", <literal>)` restores environment precedence without touching any other module, since nothing in the project imports `config.py` except `extensions.py`.

### Application and extensions (`extensions.py`)

This module owns the app and the database handle, with the app created at module scope in the direct form the rubric names:

```python
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from config import Config

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
```

`db = SQLAlchemy(app)` binds the extension to the app in one statement, satisfying Requirement 2.3 exactly as the rubric words it. `Migrate(app, db)` binds Flask-Migrate the same way.

**Why the app lives here rather than in `app.py`.** `SQLAlchemy(app)` needs `app` to already exist on the line it runs, so `db` cannot be created before the app. Meanwhile `models.py` needs `db`, `errors.py` needs `app`, and `cli.py` needs both. Putting the app and the extensions in one module whose only project import is `config` gives every other module a single stable place to import from, and means no module ever has to import back into the one that imported it. That is precisely the circular-import problem being avoided, and it is why this module is worth keeping.

The name is slightly broader than its contents suggest, since it holds the app and not only extensions. That is a deliberate trade for having exactly one import target.

**Cost of the module-level app.** With no factory there is no way to construct a second app instance with different configuration, and because the connection string is a literal in `Config`, the target database is fixed at import time. That makes isolated test configuration awkward. Automated tests are not a deliverable for this checkpoint, so the cost is acceptable; if Checkpoint 3 needs testable configuration, the escape hatch is to wrap app creation in a `create_app()` function and switch to `db.init_app(app)`, a change contained to this module and `app.py`.

### Entry point (`app.py`)

Imports the app, registers the blueprints explicitly, imports the modules that register through import side effects, and runs the development server:

```python
from extensions import app
from routes import products_bp, users_bp

import models   # noqa: F401  registers tables on the metadata
import errors   # noqa: F401  registers error handlers
import cli      # noqa: F401  registers CLI commands

app.register_blueprint(products_bp)
app.register_blueprint(users_bp)

if __name__ == "__main__":
    app.run(debug=True)
```

Blueprint registration is an explicit call, so the URL wiring is readable here rather than implied. The `# noqa: F401` markers cover `models`, `errors`, and `cli`, which a linter reads as unused while each in fact performs its registration on import. Importing `models` here is what guarantees the metadata is complete before Alembic inspects it, which Requirement 3.12 depends on.

Because `app.py` imports from `extensions` and nothing imports `app.py` back, every launch path works:

| Command | How the app is found | Debug source |
|---|---|---|
| `python app.py` | Runs the `__main__` block directly | `debug=True` in the call |
| `flask run` | Imports the module, finds the `app` attribute | `FLASK_DEBUG` only |
| `flask db ...` | Same discovery as `flask run` | n/a |
| `flask check-db` | Same discovery as `flask run` | n/a |

`flask run` never executes the `__main__` block, so `debug=True` in the code does not apply to it. To keep both paths behaving the same, `.flaskenv` sets debug alongside the app path:

```
FLASK_APP=app.py
FLASK_DEBUG=1
```

`FLASK_APP` is what lets `flask db` and the custom commands resolve the app with no extra arguments. Because the app is module-level, Flask-Migrate discovers it directly. `.flaskenv` holds only the app path and the debug flag, so it is committed; `.env`, which would hold a real `SECRET_KEY`, stays ignored.

### Models (`models.py`)

All four model classes and the `order_items` association table live in this one module, which does `from extensions import db`. Declaration order matters within the file: the `order_items` table is defined before `Order` and `Product` so their relationships can reference it directly as `secondary=order_items` without a string lookup. Each model exposes a `to_dict()` serializer used by the route layer. Column-level detail is specified in [Data Models](#data-models).

`User` exposes two additional methods:

| Method | Signature | Behavior |
|---|---|---|
| `set_password` | `set_password(self, raw_password: str) -> None` | Hashes with Werkzeug and assigns `password_hash` |
| `check_password` | `check_password(self, raw_password: str) -> bool` | Verifies a candidate password against the stored hash |

Werkzeug ships with Flask, so this adds no dependency, and its scrypt hashes stay well under the 255-character column limit. No plaintext password is ever stored, satisfying Requirement 5.2. `User.to_dict()` omits `password_hash` entirely, satisfying Requirements 5.3 and 6.3, and emits `created_at` as an ISO 8601 string.

### Routes (`routes.py`)

All routes live in this one module, organized as two blueprints:

```python
products_bp = Blueprint("products", __name__)
users_bp = Blueprint("users", __name__, url_prefix="/users")
```

Blueprints work regardless of how many route files exist, and they earn their place here for a specific reason: a blueprint is defined without an app, so `routes.py` imports only `db` and the models, never `app`. That removes a dependency edge from the import graph and leaves `extensions.py` imported by fewer modules. Registration then becomes an explicit statement in `app.py` rather than a side effect of importing the module, so the wiring is visible in one place.

`url_prefix="/users"` on the users blueprint also groups the user routes without repeating the prefix on each decorator.

**Product routes** — no database access.

| Method | Path | Success | Failure |
|---|---|---|---|
| GET | `/products` | 200, full hardcoded list via `jsonify()` | none |
| GET | `/products/<int:product_id>` | 200, single matching product | 404 JSON error |

The hardcoded data is a module-level list of dictionaries with identical keys on every entry: `id`, `name`, `category`, `price`, `stock_quantity`. Values mirror real Checkpoint 1 products so the warm-up data looks like the store, per Requirement 1.4.

**User routes** — database-backed.

| Method | Path | Success | Failure |
|---|---|---|---|
| POST | `/users/register` | 201, created user without `password_hash` | 400 invalid body or fields, 409 duplicate, 500 database error |
| GET | `/users/<int:user_id>` | 200, user without `password_hash` | 404 not found |

Register validation sequence, mapping to Requirement 5:

1. Parse the body with `request.get_json(silent=True)`. A missing or malformed body returns 400 (5.6).
2. Require non-empty `username`, `email`, and `password`; missing or blank fields return 400 with the offending field names (5.4).
3. Check for an existing user by case-insensitive username or email. A match returns 409 (5.5). The pre-check gives a clean message; the database's unique indexes remain the real guarantee.
4. Build the `User`, call `set_password`, then `db.session.add()` and `db.session.commit()` as the rubric specifies, and return 201 with `to_dict()` (5.1).
5. Wrap the write in `try/except`. `IntegrityError` returns 409 to cover the race between the pre-check and the commit; any other `SQLAlchemyError` returns 500. Both call `db.session.rollback()` first (5.7).

Retrieve uses `db.session.get(User, user_id)` and returns 404 when the result is `None`, satisfying Requirements 6.1 and 6.2. Once the `role` migration lands, `to_dict()` includes `role`, satisfying Requirement 6.5.

### CLI commands (`cli.py`)

**`flask check-db`** executes `SELECT version()` through the SQLAlchemy engine and prints the server version and the resolved target database, then reports the row count of each of the five tables. This is the live-connection verification Requirement 2.5 asks for, and it doubles as a fast confirmation that the seeded data is intact after a migration.

**`flask link-order-products`** inserts the many-to-many demonstration data for Requirement 9. Design of this command:

- It **extends an existing order rather than creating a new one.** Order 4 currently holds a single product (Windbreaker Jacket). The command adds two more products to it, so the order links three products through the association table. Creating a brand-new order would have broken the `queries.sql` integrity check that expects exactly three orders per user, whereas extending order 4 leaves that check green.
- Each inserted row sets `quantity` and `unit_price`, with `unit_price` read from the product's current price through the ORM, satisfying Requirement 9.4.
- Inserts use the PostgreSQL dialect's `on_conflict_do_nothing` against the composite primary key, so repeated runs are safe (Requirement 9.5).
- After inserting, it recomputes order 4's `total_price` from the sum of its association rows and commits. This keeps the `queries.sql` stored-versus-calculated total check passing.
- It then reloads the order through the ORM and prints `order.products`, demonstrating the relationship returns multiple products (Requirements 9.2 and 9.3).

## Data Models

Column definitions mirror `schema.sql` field for field. The mapping:

| Table | Column | Checkpoint 1 type | SQLAlchemy type |
|---|---|---|---|
| `users` | `id` | `SERIAL PRIMARY KEY` | `Integer, primary_key=True` |
| `users` | `username` | `VARCHAR(255) NOT NULL` | `String(255), nullable=False, unique=True` |
| `users` | `email` | `VARCHAR(255) NOT NULL` | `String(255), nullable=False, unique=True` |
| `users` | `password_hash` | `VARCHAR(255) NOT NULL` | `String(255), nullable=False` |
| `users` | `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | `Boolean, nullable=False, default=True, server_default=text("true")` |
| `users` | `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` | `DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()` |
| `categories` | `id` | `SERIAL PRIMARY KEY` | `Integer, primary_key=True` |
| `categories` | `name` | `VARCHAR(255) UNIQUE NOT NULL` | `String(255), nullable=False, unique=True` |
| `categories` | `description` | `TEXT` | `Text, nullable=True` |
| `products` | `category_id` | `INTEGER NOT NULL FK` | `Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False` |
| `products` | `price` | `NUMERIC(11,2) NOT NULL` | `Numeric(11, 2), nullable=False` |
| `products` | `stock_quantity` | `INTEGER NOT NULL` | `Integer, nullable=False` |
| `orders` | `user_id` | `INTEGER NOT NULL FK` | `Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False` |
| `orders` | `total_price` | `NUMERIC(14,2) NOT NULL DEFAULT 0` | `Numeric(14, 2), nullable=False, server_default=text("0")` |
| `orders` | `status` | `VARCHAR(75) NOT NULL DEFAULT 'PENDING'` | `String(75), nullable=False, server_default=text("'PENDING'")` |

`CHECK` constraints from Checkpoint 1 are declared in `__table_args__` using the names PostgreSQL generated for the inline definitions (`products_price_check`, `products_stock_quantity_check`, `orders_total_price_check`), so the models describe the same constraints the database already has.

The Checkpoint 1 case-insensitive unique indexes are declared as functional indexes in `User.__table_args__`:

```python
db.Index("uq_users_username_ci", db.func.lower(username), unique=True)
db.Index("uq_users_email_ci", db.func.lower(email), unique=True)
```

Per Requirement 3.11, `User` initially carries no `role` column. It is added in a later step so the column genuinely arrives through `flask db migrate`.

### Association table (defined in `models.py`)

Defined with `db.Table()` as Requirement 4.1 mandates, retaining the Checkpoint 1 payload columns:

```python
order_items = db.Table(
    "order_items",
    db.Column("order_id", db.Integer,
              db.ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True),
    db.Column("product_id", db.Integer,
              db.ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True),
    db.Column("quantity", db.Integer, nullable=False),
    db.Column("unit_price", db.Numeric(14, 2), nullable=False),
    db.CheckConstraint("quantity > 0", name="order_items_quantity_check"),
    db.CheckConstraint("unit_price >= 0", name="order_items_unit_price_check"),
)
```

`Order.products` and `Product.orders` are related through `secondary=order_items` with `back_populates`, satisfying Requirements 4.6 and 4.7.

**Design decision: the relationships are `viewonly=True`.** Because `quantity` and `unit_price` are `NOT NULL` with no default, `order.products.append(product)` would emit an INSERT with nulls in those columns and fail at the database. Marking the relationships read-only turns a confusing runtime integrity error into a clear, documented rule: reads go through the relationship, writes go through an explicit insert against the association table. SQLAlchemy's own guidance for an association table carrying extra columns is to use an association-object model, but the rubric requires `db.Table()`, so this is the honest compromise. Requirement 9.3 only needs the relationship to read back multiple products, which it does.

## Error Handling

Handlers registered in `errors.py` for 400, 404, 405, and 500 return a consistent JSON envelope, so an API client never receives an HTML error page:

```json
{ "error": "Not Found", "message": "User 999 was not found." }
```

| Condition | Status | Response | Session |
|---|---:|---|---|
| Unknown product id | 404 | JSON error naming the id | n/a |
| Unknown user id | 404 | JSON error naming the id | n/a |
| Body missing or not valid JSON | 400 | JSON error explaining a JSON body is required | not opened |
| Required field missing or blank | 400 | JSON error listing the offending fields | not opened |
| Duplicate username or email, pre-check | 409 | JSON error naming the conflict | not opened |
| Duplicate detected at commit (`IntegrityError`) | 409 | JSON conflict error | `rollback()` |
| Any other `SQLAlchemyError` on write | 500 | Generic JSON error, details logged not returned | `rollback()` |
| Wrong method on a valid path | 405 | JSON error | n/a |

Database failure details are logged server-side rather than returned, so internal messages and connection strings never reach a client. Every write path rolls the session back before responding, which keeps the session usable for later requests.

## Correctness Properties

These are the invariants the implementation must hold. They double as the manual verification checklist.

### Property 1: Model and database parity

With the baseline stamped and all revisions applied, `flask db migrate` produces an empty revision. Any detected difference means the models and `schema.sql` have diverged.

**Validates: Requirements 3.9, 3.10, 3.12, 4.8**

### Property 2: Seed preservation across migrations

Applying every migration leaves 10 users, 4 categories, 10 products, and 30 orders present, with `id`, `username`, `email`, and `created_at` values unchanged.

**Validates: Requirements 7.5, 8.4**

### Property 3: Role backfill totality

After the `role` revision, no user row has a null `role`.

**Validates: Requirements 8.3, 8.4**

### Property 4: Hash secrecy

`password_hash` never appears in any HTTP response body.

**Validates: Requirements 5.3, 6.3**

### Property 5: No plaintext at rest

The value submitted as `password` never appears anywhere in the `users` table.

**Validates: Requirements 5.2**

### Property 6: Registration atomicity

A failed registration leaves no partial user row behind and leaves the session usable for subsequent requests.

**Validates: Requirements 5.4, 5.5, 5.6, 5.7**

### Property 7: Association payload completeness

Every `order_items` row has non-null `quantity` and `unit_price`, with `quantity > 0` and `unit_price >= 0`.

**Validates: Requirements 4.4, 9.4**

### Property 8: Order total consistency

After `link-order-products`, each touched order's `total_price` equals the sum of `quantity * unit_price` over its association rows, so the `queries.sql` stored-versus-calculated check returns no rows.

**Validates: Requirements 9.1, 9.6**

### Property 9: Sample data idempotence

Running `link-order-products` twice produces the same association rows and the same order totals as running it once.

**Validates: Requirements 9.5**

### Property 10: Many-to-many demonstrability

At least one order loaded through the ORM returns more than one product from its products relationship.

**Validates: Requirements 4.6, 4.7, 9.2, 9.3**

### Property 11: Hardcoded route isolation

The product routes issue no SQL, so they respond successfully even when the database is unreachable.

**Validates: Requirements 1.5**

## Migration Strategy

This is the highest-risk part of the checkpoint, because the target database is already populated. The strategy is three ordered revisions.

```mermaid
graph LR
    A[Revision 1<br/>Checkpoint 1 baseline] --> B[Revision 2<br/>users unique constraints]
    B --> C[Revision 3<br/>users.role]
```

### Revision 1 — baseline

Describes the Checkpoint 1 schema exactly as it exists today: the five tables, the two case-insensitive unique indexes, and the three foreign-key indexes. It is generated by autogenerate and then reviewed by hand against `schema.sql`.

Because the tables already exist with data, this revision is **not run** against `revoshop_db`. Instead:

```
flask db stamp <revision-1>
```

That writes the revision into `alembic_version` without executing any DDL, which is what Requirements 7.3 and 7.4 call for. A reviewer starting from an empty database can instead run `flask db upgrade` and get the same schema built from scratch, so the history stays genuinely replayable. The README documents both paths.

### Revision 2 — plain unique constraints on users

Requirements 3.2 and 3.3 call for `username` and `email` to be marked unique on the model. Checkpoint 1 enforced uniqueness through functional `LOWER()` indexes rather than column constraints, so declaring `unique=True` creates a real, intentional difference between model and database. Rather than hide that, it is resolved the way the tips recommend: generate a migration, review it, apply it.

The added constraints are non-destructive. The 10 existing users contain no duplicate usernames or emails, so the constraints build cleanly. Case-insensitive protection continues to come from the existing functional indexes; the new constraints add exact-match protection and make the uniqueness visible in the model.

### Revision 3 — users.role

Adds `role` as `VARCHAR(50) NOT NULL` with `server_default='CUSTOMER'`. The server default is what makes the change safe on populated data: PostgreSQL backfills all 10 existing rows with `CUSTOMER` in the same statement, so the `NOT NULL` constraint is satisfied without a separate update and no existing column values are touched. This is what Requirements 8.3 and 8.4 require. Uppercase matches the status convention already established in Checkpoint 1.

`downgrade()` drops the column, satisfying Requirement 8.5.

After this revision the `User` model carries `role`, and `to_dict()` includes it.

### Verification after each migration

`flask check-db` prints per-table row counts, and `queries.sql` already contains integrity checks that must stay empty. The expected counts remain 10, 4, 10, 30, and 54 (rising to 56 order items after `link-order-products` adds two rows to order 4).

## Dependencies

`requirements.txt` pins the resolved versions of:

| Package | Role |
|---|---|
| `Flask` | Web framework |
| `Flask-SQLAlchemy` | ORM integration |
| `Flask-Migrate` | Alembic integration for migrations |
| `SQLAlchemy` | Core ORM, transitive but pinned for reproducibility |
| `alembic` | Migration engine, transitive but pinned |
| `psycopg2-binary` | PostgreSQL driver |
| `python-dotenv` | Required by the `flask` CLI to load `.flaskenv` |

Versions are pinned to exactly what gets installed and verified locally, rather than guessed, satisfying Requirement 10.1.

## Testing Strategy

Automated tests are not a deliverable for this checkpoint, so verification is manual and command-driven, matching what the deliverables ask to be screenshotted.

| Check | How |
|---|---|
| App starts, connection live | `flask check-db` prints the server version and row counts |
| No unintended model drift | `flask db migrate` after baselining produces an empty revision (Requirement 3.12) |
| `GET /products` | Postman; expects the full list as JSON |
| `GET /products/<id>` found and missing | Postman; expects 200 with one product, and 404 JSON |
| Register happy path | Postman POST; expects 201, no `password_hash` in the body |
| Register validation, duplicate, malformed body | Postman; expects 400, 409, 400 |
| Retrieve found and missing | Postman; expects 200 and 404 JSON |
| `role` added without data loss | `flask check-db` still reports 10 users; inspect the column in the client |
| Many-to-many | `flask link-order-products` prints three products for order 4; verify rows in the client |
| Checkpoint 1 integrity intact | Re-run `queries.sql`; the integrity checks return no rows |

The README carries example requests and expected responses for each endpoint, satisfying Requirement 11.3, plus verification queries for the `role` column and the association rows, satisfying Requirement 11.4.

## Design Decisions and Tradeoffs

| Decision | Rationale | Tradeoff |
|---|---|---|
| Module-level `db = SQLAlchemy(app)` | Matches the rubric criterion literally and keeps Flask-Migrate discovery trivial | No factory, so no per-instance configuration for tests |
| Flat modules, no packages or `__init__.py` | Fewer files to navigate for an assignment-sized project; every import path is one level deep | Would not scale to a larger codebase |
| `Config` in its own `config.py` | Conventional Flask layout; leaves room for per-environment config subclasses later | One more file than strictly needed at this size |
| `app` and `db` both in `extensions.py` | Gives every module one stable import target, so nothing imports back into its importer | The module name is broader than "extensions" implies |
| `Config` not moved into `app.py` | Would invert an edge and create a real cycle that breaks under `python app.py` | None; the separate module is also the conventional placement |
| One `models.py` and one `routes.py` | Keeps related definitions together and readable end to end | Both files grow long; `models.py` depends on declaration order for `order_items` |
| Blueprints inside the single `routes.py` | A blueprint needs no app, so `routes.py` never imports `app`; registration stays explicit in `app.py` | Two extra objects and two registration lines versus bare `@app.route` |
| Stamp the baseline instead of upgrading | The tables already exist with 108 seeded rows; running the baseline would fail | Reviewers must follow the documented stamp path on an existing database |
| Keep `quantity` and `unit_price` on `order_items` | Preserves fidelity with the Checkpoint 1 schema | A plain two-column association table would have been simpler than the rubric's minimum |
| `viewonly=True` relationships | Prevents `append()` from emitting an INSERT that violates `NOT NULL` | Writes must use an explicit insert, which the CLI command demonstrates |
| Unique constraints via their own migration | Makes the model/database difference explicit and practices the full migrate loop | One extra revision in the history |
| `role` with `server_default` | Backfills existing rows in one statement, so `NOT NULL` is safe | The column carries a server default the model must mirror |
| Extend order 4 rather than create a new order | Keeps the Checkpoint 1 three-orders-per-user integrity check green | The demonstration order is not visually "new" |
| Werkzeug for password hashing | Ships with Flask, so no added dependency | Not as configurable as `passlib` |
| Literal connection string in `config.py` | One obvious assignment line to read, matching the graded rubric's connection-string format criterion directly, with no indirection to follow | The database password is committed; unsuitable for anything deployed |
