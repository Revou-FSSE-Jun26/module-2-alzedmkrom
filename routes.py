"""Blueprints for the application's HTTP routes.

Blueprints are defined without an app, so this module never imports the
project's `app` object (it uses Flask's `current_app` proxy only to log a
500). Registration happens explicitly in `app.py`.
"""

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import User

products_bp = Blueprint("products", __name__)
users_bp = Blueprint("users", __name__, url_prefix="/users")


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


@products_bp.route("/", methods=["GET"])
def index():
    """Confirm the app is running."""
    return jsonify({"message": "RevoShop API is running."})


@products_bp.route("/products", methods=["GET"])
def list_products():
    """Return the complete hardcoded product list."""
    return jsonify(PRODUCTS)


@products_bp.route("/products/<int:product_id>", methods=["GET"])
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


# ---------------------------------------------------------------------------
# User routes: database-backed
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("username", "email", "password")


@users_bp.route("/register", methods=["POST"])
def register_user():
    """Create a new user account.

    Validation sequence (design.md, Requirement 5):
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. Require non-empty `username`, `email`, and `password`; missing or
         blank fields return 400 naming the offending fields.
      3. Case-insensitive duplicate pre-check on `username`/`email`; a match
         returns 409.
      4. Build the `User`, hash the password, `add()` + `commit()`, return
         201 with `to_dict()`.
      5. Any write failure rolls back: `IntegrityError` -> 409, any other
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
        for field in _REQUIRED_FIELDS
        if not isinstance(body.get(field), str) or not body.get(field).strip()
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

    username = body["username"].strip()
    email = body["email"].strip()
    password = body["password"]

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
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "message": "A user with that username or email already exists.",
                }
            ),
            409,
        )

    user = User(username=username, email=email)
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
