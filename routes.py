"""Blueprints for the application's HTTP routes.

Blueprints are defined without an app, so this module never imports the
project's `app` object (it uses Flask's `current_app` proxy only to log a
500). Registration happens explicitly in `app.py`.
"""

import math
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import Category, Order, Product, User, order_items

home_bp = Blueprint("home", __name__)
users_bp = Blueprint("users", __name__)
products_bp = Blueprint("products", __name__, url_prefix="/products")
categories_bp = Blueprint("categories", __name__, url_prefix="/categories")
orders_bp = Blueprint("orders", __name__, url_prefix="/orders")

# Statuses that permanently lock an order against further status changes.
# `status` itself has no fixed vocabulary (no CHECK constraint in schema.sql,
# no enum on the model column, `orders.status` is a plain VARCHAR(75)), so any
# non-blank value that fits the column is a settable target, including values
# beyond today's `PENDING`/`PROCESSING`/`SHIPPED`/`COMPLETED`/`CANCELLED` —
# e.g. `RETURNED` or `REFUNDED` if this project starts using them later. This
# set decides both when an order itself becomes locked (`update_order_status`)
# and, by extension, when a product's order history counts as fully closed
# out rather than active (`delete_product`).
_FINALIZED_ORDER_STATUSES = {"COMPLETED", "CANCELLED", "RETURNED", "REFUNDED"}

# Subset of the above that gives stock back (`update_order_status`).
# `COMPLETED` is deliberately excluded: it means the item genuinely left
# the warehouse, so its stock stays deducted.
_STOCK_RESTORING_STATUSES = {"CANCELLED", "RETURNED", "REFUNDED"}

@home_bp.route("/", methods=["GET"])
def index():
    """Confirm the app is running."""
    return jsonify({"message": "RevoShop API is running."})

# ---------------------------------------------------------------------------
# User routes: database-backed
# ---------------------------------------------------------------------------

@users_bp.route("/users", methods=["POST"])
def register_user():
    """Create a new user account.

    Validation sequence (design.md, Requirement 5):
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. Require a non-empty `username`; a missing or blank value returns
         400 naming `username`.
      3. Require a non-empty `email`; a missing or blank value returns 400
         naming `email`.
      4. Require a non-empty `password`; a missing or blank value returns
         400 naming `password`.
      5. `role` is optional. If present it must be a string of 50
         characters or fewer; a blank or omitted value falls back to the
         model's `'CUSTOMER'` server default.
      6. Case-insensitive duplicate pre-check on `username`/`email`; a match
         returns 409 naming whichever field actually conflicts.
      7. Build the `User`, hash the password, `add()` + `commit()`, return
         201 with `to_dict()`.
      8. Any write failure rolls back: `IntegrityError` -> 409, any other
         `SQLAlchemyError` -> 500.

    Note: this route has no authentication, so a caller can currently set
    its own `role` on registration. That's fine for this checkpoint (role-
    based authorization enforcement is out of scope), but it's worth
    revisiting before this ever sits behind real auth.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    username = body.get("username")
    if not isinstance(username, str) or not username.strip():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Username cannot be empty.",
                }
            ),
            400,
        )
    if len(username.strip()) > 255:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field Username must be 255 characters or fewer.",
                }
            ),
            400,
        )

    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Email cannot be empty.",
                }
            ),
            400,
        )
    if len(email.strip()) > 255:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field Email must be 255 characters or fewer.",
                }
            ),
            400,
        )

    password = body.get("password")
    if not isinstance(password, str) or not password.strip():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Password cannot be empty.",
                }
            ),
            400,
        )

    role = body.get("role")
    if role is not None and not isinstance(role, str):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'role' must be a string.",
                }
            ),
            400,
        )

    role = role.strip() if isinstance(role, str) else ""
    if len(role) > 50:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'role' must be 50 characters or fewer.",
                }
            ),
            400,
        )

    username = username.strip()
    email = email.strip()

    existing = (
        db.session.query(User)
        .filter(
            or_(
                func.lower(User.username) == username.lower(),
                func.lower(User.email) == email.lower(),
            )
        )
        .first()
    )
    if existing is not None:
        if existing.email.lower() == email.lower():
            conflict_message = "Email already exists."
        else:
            conflict_message = "Username already exists."
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": conflict_message,
                }
            ),
            409,
        )

    user = User(username=username, email=email)
    if role:
        user.role = role
    user.set_password(password)

    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "A user with that username or email already exists.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to register user: %s", exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(user.to_dict()), 201

@users_bp.route("/auth/login", methods=["POST"])
def login():
    """Authenticate a user with email and password.

    This is a placeholder implementation that mimics the behavior described
    in the design document (Requirement 6) without actually implementing
    authentication or tokens. It returns a 200 OK with the user's data,
    which is sufficient for the frontend to "log in" and display the user's
    info. A real implementation would generate a token and return it.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    email = body.get("email", "").strip()
    password = body.get("password", "")

    if not email or not password:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Email and password are required.",
                }
            ),
            400,
        )

    user = (
        db.session.query(User)
        .filter(func.lower(User.email) == email.lower())
        .first()
    )
    if user is None or not user.check_password(password):
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "message": "Invalid email or password.",
                }
            ),
            401,
        )

    return jsonify(user.to_dict())

@users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id):
    """Return the user matching `user_id`, or a 404 JSON error naming the id."""
    user = db.session.get(User, user_id)
    if user is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"User {user_id} was not found.",
                }
            ),
            404,
        )

    return jsonify(user.to_dict())


_PRODUCT_REQUIRED_FIELDS = ("category_id", "name", "price", "stock_quantity")


@products_bp.route("", methods=["POST"])
def create_product():
    """Create a new product, persisted to the database.

    Database-backed against the `Product` model, following the same
    validation shape as `register_user`:
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. Require non-null `category_id`, non-blank `name`, `price`, and
         `stock_quantity`; missing fields return 400 naming them.
      3. Type/range-check each field: `name` must be a non-blank string,
         `category_id` and `stock_quantity` must be integers (the latter
         >= 0), `price` must be a finite number >= 0, and an optional
         `description` must be a string if present.
      4. `category_id` must reference an existing `Category`, or the
         request returns 400.
      5. Build the `Product`, `add()` + `commit()`, return 201 with
         `to_dict()`.
      6. Any write failure rolls back: `IntegrityError` -> 409 (e.g. the
         category was removed between the check and the commit), any other
         `SQLAlchemyError` -> 500.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    missing = [
        field
        for field in _PRODUCT_REQUIRED_FIELDS
        if body.get(field) is None
        or (isinstance(body.get(field), str) and not body.get(field).strip())
    ]
    if missing:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Missing or blank field(s): " + ", ".join(missing),
                }
            ),
            400,
        )

    name = body["name"]
    if not isinstance(name, str) or not name.strip():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'name' must be a non-blank string.",
                }
            ),
            400,
        )
    name = name.strip()
    if len(name) > 255:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'name' must be 255 characters or fewer.",
                }
            ),
            400,
        )

    category_id = body["category_id"]
    if category_id is None:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'category_id' must be a non-blank integer.",
                }
            ),
            400,
        )
    if isinstance(category_id, bool) or not isinstance(category_id, int):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'category_id' must be an integer.",
                }
            ),
            400,
        )

    description = body.get("description")

    stock_quantity = body["stock_quantity"]
    if isinstance(stock_quantity, bool) or not isinstance(stock_quantity, int):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'stock_quantity' must be an integer.",
                }
            ),
            400,
        )
    if stock_quantity < 0:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'stock_quantity' must be zero or greater.",
                }
            ),
            400,
        )

    price = body["price"]
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'price' must be a number.",
                }
            ),
            400,
        )
    if isinstance(price, float) and not math.isfinite(price):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'price' must be a finite number.",
                }
            ),
            400,
        )
    price = Decimal(str(price))
    if price < 0:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'price' must be zero or greater.",
                }
            ),
            400,
        )

    category = db.session.get(Category, category_id)
    if category is None:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": f"category_id {category_id} does not reference an existing category.",
                }
            ),
            400,
        )

    product = Product(
        category_id=category_id,
        name=name,
        description=description,
        price=price,
        stock_quantity=stock_quantity,
    )

    try:
        db.session.add(product)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error creating product: %s", exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "The product could not be created due to a conflicting or invalid reference.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to create product: %s", exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(product.to_dict()), 201

@products_bp.route("", methods=["GET"])
def list_products():
    """Return products, ordered by id.

    Soft-deleted products (`is_delete = True`) are excluded by default,
    matching a real storefront (a soft-deleted product should not keep
    showing up for sale). Pass `?include_deleted=true` to also list them,
    e.g. for an admin view that needs to find and restore one.
    """
    query = db.session.query(Product)
    if request.args.get("include_deleted", "").strip().lower() not in ("true", "1"):
        query = query.filter(Product.is_delete.is_(False))

    products = query.order_by(Product.id).all()
    return jsonify([product.to_dict() for product in products])

@products_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    """Return the product matching `product_id`, or a 404 JSON error naming the id.

    Returned regardless of `is_delete`, so a soft-deleted product referenced
    by historical order data (see `get_order`) still resolves by id.
    """
    product = db.session.get(Product, product_id)
    if product is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Product {product_id} was not found.",
                }
            ),
            404,
        )

    return jsonify(product.to_dict())

def validate_product_data(data, require_all=True):
    if not isinstance(data, dict):
        return "Request body must be a JSON object", 400

    # ── name ───────────────────────────────────────────────────────────────
    if require_all and 'name' not in data:
        return "Missing required field: name", 400
    if 'name' in data:
        name = data['name']
        if not isinstance(name, str) or not name.strip():
            return "name cannot be empty", 422
        if len(name.strip()) > 255:
            return "name cannot exceed 255 characters", 422

    # ── price ──────────────────────────────────────────────────────────────
    if require_all and 'price' not in data:
        return "Missing required field: price", 400
    if 'price' in data:
        price = data['price']
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            return "price must be a number", 400
        if isinstance(price, float) and not math.isfinite(price):
            return "price must be a finite number", 422
        if price < 0:
            return "price must be 0 or greater", 422

    # ── stock (always optional) ───────────────────────────────────────────
    if 'stock_quantity' in data:
        stock = data['stock_quantity']
        if not isinstance(stock, int) or isinstance(stock, bool):
            return "stock must be an integer", 400
        if stock < 0:
            return "stock must be 0 or greater", 422

    # ── category_id (always optional) ─────────────────────────────────────
    if 'category_id' in data and data['category_id'] is not None:
        category_id = data['category_id']
        if not isinstance(category_id, int) or isinstance(category_id, bool) or category_id <= 0:
            return "category_id must be a positive integer", 400

    return None, None

@products_bp.route('/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Partially update a product.

    Only keys present in the body are changed. Validation is delegated to
    `validate_product_data(data, require_all=False)`, matching the shape of
    `update_category`. `category_id`, if present, must reference an existing
    `Category` or the request returns 400.
    """
    product = db.session.get(Product, product_id)
    if product is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Product {product_id} was not found.",
                }
            ),
            404,
        )

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    error, status_code = validate_product_data(data, require_all=False)
    if error:
        return jsonify({"error": "Bad Request", "message": error}), status_code

    if 'category_id' in data:
        category_id = data['category_id']
        if db.session.get(Category, category_id) is None:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": f"category_id {category_id} does not reference an existing category.",
                    }
                ),
                400,
            )
        product.category_id = category_id

    if 'name' in data:
        product.name = data['name'].strip()
    if 'description' in data:
        product.description = data['description']
    if 'price' in data:
        product.price = Decimal(str(data['price']))
    if 'stock_quantity' in data:
        product.stock_quantity = data['stock_quantity']

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error updating product %s: %s", product_id, exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "The product could not be updated due to a conflicting or invalid reference.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to update product %s: %s", product_id, exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(product.to_dict()), 200

@products_bp.route('/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product, blocked only while it has genuinely active orders.

    `order_items.product_id` has `ON DELETE RESTRICT`, which rejects a real
    row deletion the moment *any* order references the product, regardless
    of that order's status. That is too strict for "blocked if active
    orders exist": a product whose only order history is fully finalized
    (`COMPLETED`, `CANCELLED`, `RETURNED`, or `REFUNDED` —
    `_FINALIZED_ORDER_STATUSES`) should still be removable from the store.

    So this route inspects order history itself rather than letting the
    database's `RESTRICT` decide, and picks one of three outcomes:
      1. **Blocked (409)** — at least one referencing order is not
         finalized (e.g. `PENDING`, `PROCESSING`, `SHIPPED`). The product
         stays untouched.
      2. **Hard delete** — the product has never been ordered at all
         (no `order_items` rows reference it). `RESTRICT` never fires, so
         the row is actually removed.
      3. **Soft delete** — the product has order history, but every order
         referencing it is finalized. A real `DELETE` would still be
         rejected by `RESTRICT`, and erasing the association rows to force
         it would corrupt those orders' stored `total_price` (Property 8,
         design.md). Instead, `is_delete` is set to `True`: the product
         disappears from `GET /products` (default view) and can no longer
         be ordered again, while every past order that references it
         continues to resolve correctly. This is the same soft-delete
         tradeoff `delete_order` uses, and how real storefronts retire a
         SKU without destroying sales history.
    """
    product = db.session.get(Product, product_id)
    if product is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Product {product_id} was not found.",
                }
            ),
            404,
        )

    order_statuses = {
        status
        for (status,) in db.session.query(Order.status)
        .join(order_items, Order.id == order_items.c.order_id)
        .filter(order_items.c.product_id == product_id)
        .distinct()
        .all()
    }
    active_statuses = order_statuses - _FINALIZED_ORDER_STATUSES

    if active_statuses:
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": (
                        f"Product {product_id} cannot be deleted because it has "
                        "one or more active orders (status: "
                        + ", ".join(sorted(active_statuses))
                        + ")."
                    ),
                }
            ),
            409,
        )

    if order_statuses:
        # Every referencing order is finalized: soft-delete instead of
        # deleting, since RESTRICT would still reject a real row deletion.
        product.is_delete = True
        message = (
            f"Product {product_id} has only finalized orders and has been "
            "soft-deleted instead of removed, preserving order history."
        )
    else:
        # Never ordered: nothing references it, so a real delete is safe.
        db.session.delete(product)
        message = f"Product {product_id} deleted successfully."

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error deleting product %s: %s", product_id, exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "Product cannot be deleted because it still has associated orders.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete product %s: %s", product_id, exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify({"message": message}), 200


# ---------------------------------------------------------------------------
# Category routes: database-backed
# ---------------------------------------------------------------------------

@categories_bp.route("", methods=["POST"])
def create_category():
    """Create a new category.

    Validation sequence, mirroring `create_product`/`register_user`:
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. Require a non-empty `name` of 255 characters or fewer; a missing,
         blank, or oversized value returns 400 naming `name`.
      3. `description` is optional and unvalidated, matching the `categories`
         schema (`TEXT`, nullable).
      4. Duplicate pre-check on `name` (categories.name is UNIQUE, case-
         sensitive per schema.sql); a match returns 409.
      5. Build the `Category`, `add()` + `commit()`, return 201 with
         `to_dict()`.
      6. Any write failure rolls back: `IntegrityError` -> 409 (race on the
         unique constraint), any other `SQLAlchemyError` -> 500.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'name' must be a non-blank string.",
                }
            ),
            400,
        )
    name = name.strip()
    if len(name) > 255:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'name' must be 255 characters or fewer.",
                }
            ),
            400,
        )

    description = body.get("description")

    existing = db.session.query(Category).filter(Category.name == name).first()
    if existing is not None:
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "Category name already exists.",
                }
            ),
            409,
        )

    category = Category(name=name, description=description)

    try:
        db.session.add(category)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error creating category: %s", exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "Category name already exists.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to create category: %s", exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(category.to_dict()), 201

@categories_bp.route("", methods=["GET"])
def list_categories():
    """Return all categories, ordered by id."""
    categories = db.session.query(Category).order_by(Category.id).all()
    return jsonify([category.to_dict() for category in categories])

@categories_bp.route("/<int:category_id>", methods=["GET"])
def get_category(category_id):
    """Return a category along with its products, or 404 naming the id."""
    category = db.session.get(Category, category_id)
    if category is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Category {category_id} was not found.",
                }
            ),
            404,
        )

    payload = category.to_dict()
    payload["products"] = [product.to_dict() for product in category.products]
    return jsonify(payload)

@categories_bp.route("/<int:category_id>", methods=["PUT"])
def update_category(category_id):
    """Partially update a category's `name` and/or `description`.

    Only keys present in the body are changed. `name`, if present, must be
    a non-blank string of 255 characters or fewer and must not collide with
    another category's name. `description` is optional and unvalidated; if
    the key is present, its value (including explicit `null`) is stored as-is.
    """
    category = db.session.get(Category, category_id)
    if category is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Category {category_id} was not found.",
                }
            ),
            404,
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip():
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": "Field 'name' must be a non-blank string.",
                    }
                ),
                400,
            )
        name = name.strip()
        if len(name) > 255:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": "Field 'name' must be 255 characters or fewer.",
                    }
                ),
                400,
            )
        if name != category.name:
            existing = (
                db.session.query(Category)
                .filter(Category.name == name, Category.id != category_id)
                .first()
            )
            if existing is not None:
                return (
                    jsonify(
                        {
                            "error": "Conflict",
                            "message": "Category name already exists.",
                        }
                    ),
                    409,
                )
            category.name = name

    if "description" in body:
        category.description = body["description"]

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error updating category %s: %s", category_id, exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "Category name already exists.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to update category %s: %s", category_id, exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(category.to_dict()), 200

@categories_bp.route("/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    """Delete a category.

    `products.category_id` has `ON DELETE RESTRICT`, so deleting a category
    that still has products raises an `IntegrityError`, mapped to 409.
    """
    category = db.session.get(Category, category_id)
    if category is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Category {category_id} was not found.",
                }
            ),
            404,
        )

    db.session.delete(category)

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error deleting category %s: %s", category_id, exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "Category cannot be deleted because it still has associated products.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete category %s: %s", category_id, exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify({"message": f"Category {category_id} deleted successfully."}), 200


# ---------------------------------------------------------------------------
# Order routes: database-backed
# ---------------------------------------------------------------------------

_ORDER_ITEM_REQUIRED_FIELDS = ("product_id", "quantity")


@orders_bp.route("", methods=["POST"])
def create_order():
    """Place a new order.

    There is no session/token authentication in this project (see the note
    on `register_user`), so there is no server-side notion of a "logged-in
    user" to read an id from. The caller passes `user_id` explicitly in the
    body, the same way `create_product` requires an explicit `category_id`
    rather than inferring one.

    Body shape:
      {
        "user_id": 1,
        "items": [
          {"product_id": 2, "quantity": 1},
          {"product_id": 4, "quantity": 2}
        ]
      }

    Validation sequence:
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. Require a non-blank integer `user_id` referencing an existing
         `User`; missing, wrong-typed, or unknown returns 400.
      3. Require a non-empty list `items`; missing, wrong-typed, or empty
         returns 400.
      4. Each entry must be an object with an integer `product_id`
         referencing an existing `Product` and an integer `quantity > 0`;
         any violation returns 400 naming the offending item. The same
         `product_id` cannot repeat across items, since `order_items` has a
         composite primary key on `(order_id, product_id)`. Each item's
         `quantity` must also not exceed that product's current
         `stock_quantity`; any shortfall returns 400 naming the item and
         the amount actually in stock. The whole order is rejected if any
         single item fails this check (all-or-nothing, no partial order).
      5. Build the `Order` (status defaults to the model's `'PENDING'`
         server default), flush to obtain its id, then insert one
         `order_items` row per item with `unit_price` read from the
         product's current `price`, and decrement that product's
         `stock_quantity` by the ordered quantity. `total_price` is the sum
         of `quantity * unit_price` over the inserted rows.
      6. Any write failure rolls back: `IntegrityError` -> 409, any other
         `SQLAlchemyError` -> 500.

    Stock is restored if the order is later moved to `CANCELLED`,
    `RETURNED`, or `REFUNDED` — see `update_order_status`. It is not
    restored on `COMPLETED`, since that means the item genuinely left the
    warehouse.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    user_id = body.get("user_id")
    if user_id is None or isinstance(user_id, bool) or not isinstance(user_id, int):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'user_id' must be a non-blank integer.",
                }
            ),
            400,
        )

    user = db.session.get(User, user_id)
    if user is None:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": f"user_id {user_id} does not reference an existing user.",
                }
            ),
            400,
        )

    items = body.get("items")
    if not isinstance(items, list) or not items:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'items' must be a non-empty list.",
                }
            ),
            400,
        )

    seen_product_ids = set()
    validated_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": f"items[{index}] must be an object.",
                    }
                ),
                400,
            )

        missing = [
            field for field in _ORDER_ITEM_REQUIRED_FIELDS if item.get(field) is None
        ]
        if missing:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": f"items[{index}] missing field(s): " + ", ".join(missing),
                    }
                ),
                400,
            )

        product_id = item["product_id"]
        if isinstance(product_id, bool) or not isinstance(product_id, int):
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": f"items[{index}].product_id must be an integer.",
                    }
                ),
                400,
            )

        if product_id in seen_product_ids:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": (
                            f"product_id {product_id} appears more than once; "
                            "combine quantities into a single item instead."
                        ),
                    }
                ),
                400,
            )
        seen_product_ids.add(product_id)

        quantity = item["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": f"items[{index}].quantity must be an integer.",
                    }
                ),
                400,
            )
        if quantity <= 0:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": f"items[{index}].quantity must be greater than zero.",
                    }
                ),
                400,
            )

        product = db.session.get(Product, product_id)
        if product is None:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": (
                            f"items[{index}].product_id {product_id} does not "
                            "reference an existing product."
                        ),
                    }
                ),
                400,
            )

        if product.stock_quantity < quantity:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": (
                            f"items[{index}].product_id {product_id} has only "
                            f"{product.stock_quantity} in stock, which is less "
                            f"than the requested quantity ({quantity})."
                        ),
                    }
                ),
                400,
            )

        validated_items.append((product, quantity))

    order = Order(user_id=user_id)

    try:
        db.session.add(order)
        db.session.flush()

        total_price = Decimal("0")
        for product, quantity in validated_items:
            unit_price = product.price
            db.session.execute(
                order_items.insert().values(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )
            product.stock_quantity -= quantity
            total_price += unit_price * quantity

        order.total_price = total_price
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error creating order: %s", exc)
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "The order could not be created due to a conflicting or invalid reference.",
                }
            ),
            409,
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to create order: %s", exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(order.to_dict()), 201

@orders_bp.route("", methods=["GET"])
def list_orders():
    """Return orders for a user, ordered by id.

    There is no session/token authentication in this project, so the
    "current user" is whoever the caller names in the required `user_id`
    query parameter, e.g. `GET /orders?user_id=1`.

    Soft-deleted orders (`is_delete = True`) are excluded by default. Pass
    `?include_deleted=true` to also list them.
    """
    raw_user_id = request.args.get("user_id")
    if raw_user_id is None or not raw_user_id.isdigit():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Query parameter 'user_id' must be a positive integer.",
                }
            ),
            400,
        )
    user_id = int(raw_user_id)

    user = db.session.get(User, user_id)
    if user is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"User {user_id} was not found.",
                }
            ),
            404,
        )

    query = db.session.query(Order).filter(Order.user_id == user_id)
    if request.args.get("include_deleted", "").strip().lower() not in ("true", "1"):
        query = query.filter(Order.is_delete.is_(False))

    orders = query.order_by(Order.id).all()
    return jsonify([order.to_dict() for order in orders])

@orders_bp.route("/<int:order_id>", methods=["GET"])
def get_order(order_id):
    """Return an order with its order items and product details, or 404.

    Returned regardless of `is_delete`, so a soft-deleted order still
    resolves by id (e.g. from a receipt or admin recovery view), the same
    way `get_product` ignores `is_delete` for products.

    `order_items` carries `quantity` and `unit_price` alongside the
    `Product`/`Order` foreign keys, so the item rows are read directly from
    the association table (Core `select()`, matching `cli.py`) rather than
    through the `viewonly` `Order.products` relationship, which only
    resolves to `Product` objects and drops the per-row quantity/price.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Order {order_id} was not found.",
                }
            ),
            404,
        )

    item_rows = db.session.execute(
        select(
            order_items.c.product_id,
            order_items.c.quantity,
            order_items.c.unit_price,
        )
        .where(order_items.c.order_id == order_id)
        .order_by(order_items.c.product_id)
    ).all()

    payload = order.to_dict()
    payload["items"] = [
        {
            "quantity": row.quantity,
            "unit_price": float(row.unit_price),
            "product": db.session.get(Product, row.product_id).to_dict(),
        }
        for row in item_rows
    ]
    return jsonify(payload)

@orders_bp.route("/<int:order_id>", methods=["PUT"])
def update_order_status(order_id):
    """Update an order's `status`. This is the only field a client may change.

    Industry practice, and the reason this route is status-only: an order's
    line items and `unit_price` are a record of what was actually charged at
    checkout, and `total_price` is derived from them (Property 8, design.md).
    None of that should be client-editable after the fact; if the contents
    of an order need to change, that is a new order, a cancellation, or a
    refund, not a mutation of the original row. `status` is the one column
    on `Order` that legitimately changes over time.

    Validation sequence:
      1. 404 if the order does not exist.
      2. 409 if the order's *current* status is already finalized
         (`COMPLETED`, `CANCELLED`, `RETURNED`, or `REFUNDED`) — once an
         order reaches a finalized state it is locked, regardless of what
         the request is trying to change it to. This includes attempting to
         re-set the same finalized status again.
      3. 400 if the body is missing/malformed, or `status` is missing, not
         a string, blank, or over 75 characters (`orders.status` is
         `VARCHAR(75)`). There is no fixed vocabulary beyond that: any
         other non-blank value is accepted, so this project can introduce
         new statuses (e.g. `RETURNED`, `REFUNDED`) without a code change
         here. Input is normalized to uppercase to match the existing
         convention (`'PENDING'`, `'CANCELLED'`, etc. in schema.sql).
      4. Commit and return 200 with `to_dict()`.

    Note: because there is no fixed vocabulary, this route accepts values
    `queries.sql`'s "unexpected order statuses" check does not expect. That
    check is advisory, not a database constraint, so it would need its own
    allowed-list updated if new statuses are intentionally introduced.

    If the new status is `CANCELLED`, `RETURNED`, or `REFUNDED`
    (`_STOCK_RESTORING_STATUSES`), every item's `quantity` on this order is
    added back to its product's `stock_quantity`, undoing the deduction
    `create_order` made. `COMPLETED` does not restore stock. Because
    status is locked once finalized (step 2 above), this can only fire
    once per order.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Order {order_id} was not found.",
                }
            ),
            404,
        )

    if order.status in _FINALIZED_ORDER_STATUSES:
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": (
                        f"Order {order_id} is {order.status} and can no longer "
                        "be updated."
                    ),
                }
            ),
            409,
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "A valid JSON body is required.",
                }
            ),
            400,
        )

    status = body.get("status")
    if not isinstance(status, str) or not status.strip():
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'status' must be a non-blank string.",
                }
            ),
            400,
        )

    status = status.strip().upper()
    if len(status) > 75:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Field 'status' must be 75 characters or fewer.",
                }
            ),
            400,
        )

    order.status = status

    try:
        if status in _STOCK_RESTORING_STATUSES:
            item_rows = db.session.execute(
                select(order_items.c.product_id, order_items.c.quantity)
                .where(order_items.c.order_id == order_id)
            ).all()
            for row in item_rows:
                product = db.session.get(Product, row.product_id)
                if product is not None:
                    product.stock_quantity += row.quantity

        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to update order %s: %s", order_id, exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(order.to_dict()), 200

@orders_bp.route("/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    """Soft-delete an order: set `is_delete = True`, no row removed.

    Unconditional. Unlike `delete_product`, this does not inspect `status`
    first; any order, in any status, is soft-deleted on request. The row,
    and every `order_items` row under it, stays in the database forever, so
    order history, totals, and accounting records are never lost. A
    soft-deleted order is hidden from `list_orders` by default but still
    resolves through `get_order` by id.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return (
            jsonify(
                {
                    "error": "Not Found",
                    "message": f"Order {order_id} was not found.",
                }
            ),
            404,
        )

    order.is_delete = True

    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete order %s: %s", order_id, exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify({"message": f"Order {order_id} deleted successfully."}), 200
