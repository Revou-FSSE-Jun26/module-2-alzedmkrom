"""Blueprints for the application's HTTP routes.

Blueprints are defined without an app, so this module never imports the
project's `app` object (it uses Flask's `current_app` proxy only to log a
500). Registration happens explicitly in `app.py`.
"""

import math
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    current_user,
    decode_token,
    get_jwt,
    jwt_required,
)
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth import (
    admin_required,
    forbid_unless_self_or_admin,
    is_admin,
    revoke_current_token,
    revoke_token,
)
from extensions import db, limiter
from models import Category, Order, Product, User, normalize_password, order_items

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
@limiter.limit(lambda: current_app.config["RATELIMIT_REGISTER"])
@jwt_required(optional=True)
def register_user():
    """Create a new user account.

    Validation sequence (design.md, Requirement 5):
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. Require a non-empty `username`; a missing or blank value returns
         400 naming `username`.
      3. Require a non-empty `email`; a missing or blank value returns 400
         naming `email`.
      4. Require a non-empty `password` that satisfies
         `_password_policy_error` (minimum length, at least one letter, at
         least one digit); a missing, blank, or weak value returns 400, the
         last with `"code": "weak_password"`.
      5. `role` is **only honored for an authenticated admin caller**. See
         the note below.
      6. Case-insensitive duplicate pre-check on `username`/`email`; a match
         returns 409 naming whichever field actually conflicts.
      7. Build the `User`, hash the password, `add()` + `commit()`, return
         201 with `to_dict()`.
      8. Any write failure rolls back: `IntegrityError` -> 409, any other
         `SQLAlchemyError` -> 500.

    Registration stays open to anonymous callers — a storefront has to let
    people sign up — but `role` no longer is. Now that `role` decides who may
    edit the catalog (see `admin_required`), honoring a caller-supplied
    `role` here would let anyone mint themselves an admin account with a
    single unauthenticated POST. So the token is inspected optionally: an
    admin may set `role` (useful for creating the first colleague account),
    and everyone else silently gets the model's `'CUSTOMER'` default, even if
    they sent something else.
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

    policy_error = _password_policy_error(password)
    if policy_error is not None:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": policy_error,
                    "code": "weak_password",
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

    # Privilege escalation guard: drop a caller-supplied role unless the
    # request carries an admin token. Silently ignored rather than rejected,
    # so an ordinary signup that happens to include `role` still succeeds
    # (as a CUSTOMER) instead of failing with a confusing 403.
    if role and not is_admin(current_user):
        role = ""

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

def _issue_tokens(user):
    """Mint a fresh access/refresh pair for `user` and describe their lifetimes.

    `expires_in` / `refresh_expires_in` are seconds, included so a frontend can
    schedule a refresh slightly before the access token lapses instead of
    waiting to be surprised by a 401. `role` is copied into the access token as
    a claim for convenience, but authorization never trusts it: every guard
    re-reads the user from the database (see `auth._user_lookup`), so demoting
    or deactivating an account takes effect on the account's next request
    rather than whenever its current token happens to expire.
    """
    access_token = create_access_token(
        identity=user, additional_claims={"role": user.role}
    )
    refresh_token = create_refresh_token(identity=user)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": int(
            current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()
        ),
        "refresh_expires_in": int(
            current_app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds()
        ),
        "user": user.to_dict(),
    }


@users_bp.route("/auth/login", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_LOGIN"])
def login():
    """Exchange email and password for an access/refresh token pair.

    Rate limited more tightly than anything else in the app, because this is
    the one endpoint where an attacker needs no credentials to start: every
    role check elsewhere is moot once someone has guessed an admin's password.
    Exceeding the limit returns 429 with `"code": "rate_limit_exceeded"` and a
    `Retry-After` header.

    Response body:
      {
        "access_token": "...",        # send as: Authorization: Bearer <token>
        "refresh_token": "...",       # only usable at POST /auth/refresh
        "token_type": "Bearer",
        "expires_in": 900,            # access token lifetime, seconds
        "refresh_expires_in": 604800, # refresh token lifetime, seconds
        "user": { ... }
      }

    A wrong email and a wrong password return the same 401 with the same
    message, so the response cannot be used to enumerate which accounts
    exist. A deactivated account (`is_active = false`) is refused here too,
    with a distinct message, since that is a state the account holder can
    act on rather than a credential mistake.
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

    email = body.get("email")
    password = body.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "message": "Email and password are required.",
                }
            ),
            400,
        )

    email = email.strip()
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
                    "code": "invalid_credentials",
                }
            ),
            401,
        )

    if not user.is_active:
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "message": "This account has been deactivated.",
                    "code": "account_inactive",
                }
            ),
            401,
        )

    return jsonify(_issue_tokens(user)), 200


@users_bp.route("/auth/refresh", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_REFRESH"])
@jwt_required(refresh=True)
def refresh():
    """Trade a valid refresh token for a new access/refresh pair.

    Called with the **refresh** token in the Authorization header, not the
    access token.

    The refresh token presented is revoked as part of issuing the new pair
    (refresh-token rotation). Two things follow from that:

    * Each token is single-use, so one captured from storage or a log is
      worthless the moment the real client refreshes again — and a replay of
      an already-rotated token comes back as `token_revoked`.
    * The session's idle timeout slides. An active client keeps trading its
      way forward indefinitely, while a client that goes quiet for longer
      than `JWT_REFRESH_MINUTES` finds its refresh token expired and has to
      log in again. That expiry is the auto-logout: this endpoint answers
      401 `token_expired` with `"token_type": "refresh"`, which is a
      frontend's cue to clear both tokens and show the login screen.
    """
    revoke_current_token()

    payload = _issue_tokens(current_user)

    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to rotate refresh token: %s", exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return jsonify(payload), 200


@users_bp.route("/auth/logout", methods=["POST"])
@jwt_required()
def logout():
    """Revoke the caller's tokens, ending the session immediately.

    Called with the **access** token in the Authorization header. Because a
    JWT stays valid until its own expiry, "logging out" client-side by
    forgetting the tokens would leave them usable by anyone who had copied
    them; both are therefore recorded in `token_blocklist` and rejected from
    here on.

    The access token is always revoked. The refresh token is only revoked if
    the client also sends it in the body:

        {"refresh_token": "<the refresh token>"}

    Clients should send it — skipping it leaves a working refresh token that
    can mint new access tokens, so the session would not really be over. A
    malformed or already-expired value there is ignored rather than rejected:
    the point of logout is that the caller ends up logged out, so it answers
    200 as long as the access token was revoked.
    """
    revoked = {"access": revoke_current_token(), "refresh": False}

    body = request.get_json(silent=True)
    if isinstance(body, dict) and isinstance(body.get("refresh_token"), str):
        try:
            decoded = decode_token(body["refresh_token"])
        except Exception:  # noqa: BLE001 - any bad token is simply skipped
            decoded = None
        # Only the caller's own refresh token may be revoked here, so a
        # captured token belonging to somebody else cannot be used to log
        # that person out.
        if (
            decoded is not None
            and decoded.get("type") == "refresh"
            and str(decoded.get("sub")) == str(current_user.id)
        ):
            revoked["refresh"] = revoke_token(decoded)

    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to revoke token(s) on logout: %s", exc)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An internal error occurred. Please try again later.",
                }
            ),
            500,
        )

    return (
        jsonify(
            {
                "message": "Logged out successfully.",
                "revoked": revoked,
            }
        ),
        200,
    )


@users_bp.route("/auth/me", methods=["GET"])
@jwt_required()
def me():
    """Return the account behind the access token.

    Lets a frontend restore its session on reload: it has a stored token but
    no user object, and this resolves one without a second login. Also the
    cheapest way for a client to find out whether its token is still good.
    """
    return jsonify(current_user.to_dict()), 200

@users_bp.route("/users/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    """Return the user matching `user_id`, restricted to that user or an admin.

    The ownership check runs before the existence check on purpose: answering
    404 for a stranger's id and 403 for a real one would turn this endpoint
    into a way to enumerate which accounts exist. Non-owners get 403 either
    way, and only the account holder (or an admin) can tell a missing id from
    a present one.
    """
    forbidden = forbid_unless_self_or_admin(user_id)
    if forbidden is not None:
        return forbidden

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


def _password_policy_error(password):
    """Return why `password` is unacceptable, or None if it passes.

    The rule is a length between `PASSWORD_MIN_LENGTH` (default 8) and
    `PASSWORD_MAX_LENGTH` (default 255), plus at least one letter and at least
    one digit. No uppercase character is required.

    Three deliberate choices:

    * **Everything is measured on the Unicode-normalised password**, which is
      what actually gets hashed. Validating the raw input instead would let
      the two encodings of the same visible password disagree about whether
      they satisfy the rules.
    * **Length is not measured on a stripped string**, because a space is a
      perfectly good password character and silently not counting it would
      make the limit a lie. An all-whitespace password still fails, on the
      letter and digit rules.
    * **Case is not part of the rule, but passwords stay case-sensitive.**
      Nothing here lowercases anything, and normalisation does not fold case,
      so `secret1` and `Secret1` remain different passwords.

    Each failure names the one rule that was broken rather than reciting the
    whole policy, so a caller fixing a short password is not also told about
    digits it already has.

    Applied by `register_user` only. Login must never call this: accounts
    created before the policy existed have working passwords that would not
    satisfy it, and re-checking at login would lock them out of their own
    accounts rather than prompting anyone to choose a better one.
    """
    # Checked against the normalised form, because that is the string
    # `set_password` will hash. Measuring the raw input instead would let a
    # decomposed password fail a length rule that its stored form satisfies.
    password = normalize_password(password)

    minimum = current_app.config["PASSWORD_MIN_LENGTH"]
    maximum = current_app.config["PASSWORD_MAX_LENGTH"]
    if len(password) < minimum:
        return f"Password must be at least {minimum} characters long."
    if len(password) > maximum:
        return f"Password must be {maximum} characters or fewer."
    if not any(character.isalpha() for character in password):
        return "Password must contain at least one letter."
    if not any(character.isdigit() for character in password):
        return "Password must contain at least one number."
    return None


_PRODUCT_REQUIRED_FIELDS = ("category_id", "name", "price", "stock_quantity")


@products_bp.route("", methods=["POST"])
@admin_required
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
@jwt_required(optional=True)
def list_products():
    """Return products, ordered by id. Public: no token required.

    Soft-deleted products (`is_delete = True`) are excluded by default,
    matching a real storefront (a soft-deleted product should not keep
    showing up for sale). `?include_deleted=true` also lists them, for an
    admin view that needs to find and restore one — and is therefore honored
    only for an admin caller. Anyone else passing it gets the normal public
    listing rather than a 403, since it is a display preference, not an
    action being refused.
    """
    query = db.session.query(Product)
    wants_deleted = request.args.get("include_deleted", "").strip().lower() in (
        "true",
        "1",
    )
    if not (wants_deleted and is_admin(current_user)):
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@jwt_required()
def create_order():
    """Place a new order for the authenticated user.

    The order's owner is taken from the access token, not from the request
    body. An earlier version of this endpoint read `user_id` out of the body
    because the project had no authentication; keeping that now would mean any
    caller could place orders in anyone else's name just by changing a number,
    so a `user_id` in the body is ignored. There is deliberately no
    "order on behalf of" path, not even for admins.

    Body shape:
      {
        "items": [
          {"product_id": 2, "quantity": 1},
          {"product_id": 4, "quantity": 2}
        ]
      }

    Validation sequence:
      1. Parse the body with `request.get_json(silent=True)`; a missing or
         malformed body returns 400.
      2. The owner comes from the token; `current_user` is guaranteed to
         exist and be active by the time this runs (see `auth._user_lookup`).
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

    # Owner comes from the verified token, never from the body.
    user_id = current_user.id

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
@jwt_required()
def list_orders():
    """Return the authenticated user's orders, ordered by id.

    `user_id` used to be a required query parameter, because there was no
    authentication and the caller had to say who they were. It is now taken
    from the access token, so `GET /orders` returns your own orders and
    nothing else — a customer cannot read someone else's order history by
    changing the number.

    An admin may still pass `?user_id=<id>` to read a specific customer's
    orders; for any other caller that parameter is refused with 403 rather
    than quietly ignored, since silently returning your own orders when you
    asked for someone else's would be misleading.

    Soft-deleted orders (`is_delete = True`) are excluded by default. Pass
    `?include_deleted=true` to also list them.
    """
    user_id = current_user.id

    raw_user_id = request.args.get("user_id")
    if raw_user_id is not None:
        if not raw_user_id.isdigit():
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": "Query parameter 'user_id' must be a positive integer.",
                    }
                ),
                400,
            )
        requested_id = int(raw_user_id)
        forbidden = forbid_unless_self_or_admin(requested_id)
        if forbidden is not None:
            return forbidden
        user_id = requested_id

        if db.session.get(User, user_id) is None:
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
@jwt_required()
def get_order(order_id):
    """Return an order with its order items and product details, or 404.

    Readable only by the user the order belongs to, or by an admin: order
    history includes what was bought and what was charged, so ids must not be
    guessable into other people's receipts.

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

    forbidden = forbid_unless_self_or_admin(order.user_id)
    if forbidden is not None:
        return forbidden

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
@admin_required
def update_order_status(order_id):
    """Update an order's `status`. This is the only field a client may change.

    Admin-only. Status drives fulfilment and, for the stock-restoring
    statuses, moves inventory back: letting a customer set their own order to
    `CANCELLED` would hand them a way to return stock to the catalogue at
    will, and setting it to `COMPLETED` would mark goods as shipped that
    never were.

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
@jwt_required()
def delete_order(order_id):
    """Soft-delete an order: set `is_delete = True`, no row removed.

    Allowed for the order's owner (hiding an order from their own history) or
    an admin.

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

    forbidden = forbid_unless_self_or_admin(order.user_id)
    if forbidden is not None:
        return forbidden

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
