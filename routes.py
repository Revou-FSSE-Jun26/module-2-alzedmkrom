"""Blueprints for the application's HTTP routes.

Blueprints are defined without an app, so this module never imports the
project's `app` object (it uses Flask's `current_app` proxy only to log a
500). Registration happens explicitly in `app.py`.
"""

import math
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import Category, Product, User

home_bp = Blueprint("home", __name__)
users_bp = Blueprint("users", __name__)
products_bp = Blueprint("products", __name__, url_prefix="/products")
categories_bp = Blueprint("categories", __name__, url_prefix="/categories")
orders_bp = Blueprint("orders", __name__, url_prefix="/orders")

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


# Hardcoded warm-up data: a list of dictionaries where every entry carries the
# same keys. Values mirror the real Checkpoint 1 products from seed.sql, with
# `category` resolved from the seeded category rows. These routes issue no SQL.
PRODUCTS = [
    {
        "id": 1,
        "name": "Nike Air Max Running Shoes",
        "category": "Footwear",
        "price": 850000.00,
        "stock_quantity": 50,
    },
    {
        "id": 2,
        "name": "Plain Cotton Combed T-Shirt",
        "category": "Apparel",
        "price": 75000.00,
        "stock_quantity": 200,
    },
    {
        "id": 3,
        "name": "Fleece Jogger Pants",
        "category": "Apparel",
        "price": 195000.00,
        "stock_quantity": 80,
    },
    {
        "id": 4,
        "name": "Unisex Baseball Cap",
        "category": "Accessories",
        "price": 120000.00,
        "stock_quantity": 150,
    },
    {
        "id": 5,
        "name": "Windbreaker Jacket",
        "category": "Apparel",
        "price": 450000.00,
        "stock_quantity": 30,
    },
    {
        "id": 6,
        "name": "Sports Socks 3-Pack",
        "category": "Footwear",
        "price": 55000.00,
        "stock_quantity": 300,
    },
    {
        "id": 7,
        "name": "Waterproof Backpack",
        "category": "Bags",
        "price": 320000.00,
        "stock_quantity": 60,
    },
    {
        "id": 8,
        "name": "UV400 Sunglasses",
        "category": "Accessories",
        "price": 135000.00,
        "stock_quantity": 100,
    },
    {
        "id": 9,
        "name": "Digital Sports Watch",
        "category": "Accessories",
        "price": 275000.00,
        "stock_quantity": 45,
    },
    {
        "id": 10,
        "name": "Leather Belt",
        "category": "Accessories",
        "price": 180000.00,
        "stock_quantity": 75,
    },
]

_PRODUCT_REQUIRED_FIELDS = ("category_id", "name", "price", "stock_quantity")


@products_bp.route("", methods=["POST"])
def create_product():
    """Create a new product, persisted to the database.

    Unlike the hardcoded `GET` routes above, this route is database-backed
    against the `Product` model, following the same validation shape as
    `register_user`:
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
    if len(name.strip()) > 255:
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
    """Return the complete hardcoded product list."""
    return jsonify(PRODUCTS)

@products_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    """Return the single hardcoded product matching `product_id`, or 404."""
    for product in PRODUCTS:
        if product["id"] == product_id:
            return jsonify(product)

    return (
        jsonify(
            {
                "error": "Not Found",
                "message": f"Product {product_id} was not found.",
            }
        ),
        404,
    )

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
    # TODO: Fetch product, update fields from data, commit, return updated product
    product = Product.query.get(product_id)
    if product is None:
        return jsonify({'error': f'Product {product_id} not found'}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body must be JSON'}), 400

    # TODO 3: call validate_product_data(data, require_all=False) and return error if any
    error, status_code = validate_product_data(data, require_all=False)
    if error:
        return jsonify({'error': error}), status_code

    if data.get('name') is not None:
        product.name = data['name']
    product.sku = data['description']
    if data.get('price') is not None:
        product.price = data['price']
    if data.get('stock_quantity') is not None:
        product.stock = data['stock']
    if data.get('category_id') is not None:
        product.category_id = data['category_id']

    try:
        db.session.commit()
        return jsonify(product.to_dict()), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'SKU already exists'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "detail": str(e)}), 500

@products_bp.route('/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    # TODO: Fetch product, delete from session, commit, return confirmation
    product = Product.query.get(product_id)
    if product is None:
        return jsonify({'error': f'Product {product_id} not found'}), 404

    db.session.delete(product)

    try:
        db.session.commit()
        return jsonify({'message': 'Product deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "detail": str(e)}), 500

