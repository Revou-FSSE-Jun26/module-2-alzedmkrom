"""SQLAlchemy models mirroring the Checkpoint 1 `revoshop_db` schema.

The database is the source of truth: every column type, nullability, default,
numeric precision, constraint name, and index name here is written to match
`schema.sql` exactly, so autogenerate reports no unintended differences.

`order_items` is declared first with ``db.Table()`` so the ``Order`` and
``Product`` relationships can reference it directly as ``secondary=order_items``
without a string lookup.
"""

import unicodedata

from sqlalchemy import func, text
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def normalize_password(raw_password: str) -> str:
    """Return `raw_password` in Unicode NFKC form, ready to be hashed.

    Without this, a password containing any non-ASCII character can lock its
    own owner out. The same visible character often has more than one valid
    encoding — ``é`` is either one code point (U+00E9) or two (``e`` plus a
    combining acute) — and the two spell the same word on screen while being
    different strings underneath. Hash one and compare the other and
    verification fails, so whether login works comes down to which keyboard,
    operating system, or paste buffer the password happened to arrive through.
    Nothing in the response could explain that to the user.

    Normalising both on the way in and on the way out removes the ambiguity;
    it is what NIST SP 800-63B asks for when Unicode is accepted in memorized
    secrets (NFKC or NFKD — NFKC is used here, being the composed form).

    NFKC also applies compatibility folding, which is worth knowing about
    because it is mildly lossy: ``²`` becomes ``2`` and full-width ``ｐ``
    becomes ``p``, so two passwords that look different can normalise to the
    same string. That is the intended trade — a slightly smaller password
    space in exchange for a password that keeps working wherever it is typed.

    Applies to every path that sets or checks a password, which is why it
    lives here next to them rather than in the route.
    """
    return unicodedata.normalize("NFKC", raw_password)

# ---------------------------------------------------------------------------
# Association table: orders <-> products (many-to-many with payload columns)
# ---------------------------------------------------------------------------

order_items = db.Table(
    "order_items",
    db.Column(
        "order_id",
        db.Integer,
        db.ForeignKey("orders.id", ondelete="CASCADE", name="fk_items_order"),
        primary_key=True,
        nullable=False,
    ),
    db.Column(
        "product_id",
        db.Integer,
        db.ForeignKey("products.id", ondelete="RESTRICT", name="fk_items_product"),
        primary_key=True,
        nullable=False,
    ),
    db.Column("quantity", db.Integer, nullable=False),
    db.Column("unit_price", db.Numeric(14, 2), nullable=False),
    db.CheckConstraint("quantity > 0", name="order_items_quantity_check"),
    db.CheckConstraint("unit_price >= 0", name="order_items_unit_price_check"),
    # order_items.order_id is already covered by the composite primary key.
    db.Index("idx_order_items_product_id", "product_id"),
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class User(db.Model):
    """A RevoShop account.

    ``role`` was added through a reviewed Flask-Migrate revision (revision
    3, ``67d9a832861f``) rather than being present from the start. That
    revision has been applied to `revoshop_db`, backfilling all existing
    rows with ``'CUSTOMER'``.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    role = db.Column(
        db.String(50),
        nullable=False,
        server_default=text("'CUSTOMER'"),
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    # Checkpoint 1 enforces case-insensitive uniqueness with functional indexes.
    __table_args__ = (
        db.Index("uq_users_username_ci", func.lower(username), unique=True),
        db.Index("uq_users_email_ci", func.lower(email), unique=True),
    )

    orders = db.relationship("Order", back_populates="user")

    def set_password(self, raw_password: str) -> None:
        """Hash ``raw_password`` with Werkzeug and store it on ``password_hash``.

        No plaintext password is ever stored (Requirement 5.2). The password is
        Unicode-normalised first — see ``normalize_password`` — so that it can
        be verified later regardless of how the same characters get encoded on
        the way in.
        """
        self.password_hash = generate_password_hash(normalize_password(raw_password))

    def check_password(self, raw_password: str) -> bool:
        """Verify ``raw_password`` against the stored hash.

        Normalises exactly as ``set_password`` does; the two have to agree or
        non-ASCII passwords would verify only by luck.
        """
        return check_password_hash(
            self.password_hash, normalize_password(raw_password)
        )

    def to_dict(self) -> dict:
        """Serialize the user, omitting ``password_hash`` entirely.

        Satisfies Requirements 5.3 and 6.3. ``created_at`` is emitted as an
        ISO 8601 string. ``role`` is included now that the revision adding
        the column has been applied (Requirement 6.5).
        """
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User {self.id} {self.username}>"


class TokenBlocklist(db.Model):
    """A JWT that has been revoked before its own expiry.

    JWTs are self-contained: the server does not store a session, so a token
    stays valid until its `exp` passes. That makes a real logout impossible
    without recording revocations somewhere, which is what this table is for.
    ``auth.py`` registers a ``token_in_blocklist_loader`` that looks up every
    incoming token's ``jti`` here.

    It is a database table rather than an in-process set because neither of
    the two things that would break an in-memory blocklist is avoidable in
    this deployment: gunicorn runs more than one worker (a token revoked in
    one worker would still be accepted by the others), and a restart or
    redeploy would silently un-revoke everything.

    Rows outlive the token only until ``expires_at``; after that the token is
    rejected on its own expiry and the row is just clutter. ``flask
    prune-tokens`` (see cli.py) deletes those.
    """

    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)

    # The JWT ID claim: a UUID4 string that flask-jwt-extended puts in every
    # token it mints, unique per token.
    jti = db.Column(db.String(36), nullable=False, unique=True)

    # 'access' or 'refresh', kept for auditing and so logout can report which
    # token types it actually revoked.
    token_type = db.Column(db.String(16), nullable=False)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE", name="fk_blocklist_user"),
        nullable=False,
    )

    # Mirrors the token's own `exp`, so expired rows can be pruned without
    # decoding anything.
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)

    revoked_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        # Every authenticated request looks a jti up here, so this index is on
        # the hot path rather than a nicety.
        db.Index("idx_token_blocklist_jti", "jti"),
        db.Index("idx_token_blocklist_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<TokenBlocklist {self.token_type} user={self.user_id}>"


class Category(db.Model):
    """A product category."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)

    products = db.relationship("Product", back_populates="category")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"<Category {self.id} {self.name}>"


class Product(db.Model):
    """An item for sale, belonging to exactly one category.

    ``is_delete`` was added through a reviewed Flask-Migrate revision,
    following the same pattern as ``User.role``. It backs the soft-delete
    behavior in ``DELETE /products/<id>``: a product with order history that
    is entirely finalized (Requirement: DELETE /products/<id> blocked only
    by *active* orders) is soft-deleted rather than removed, since
    ``order_items.product_id`` has ``ON DELETE RESTRICT`` and would reject a
    real row deletion regardless of the referencing orders' status.

    This column previously existed as ``is_active`` (inverted polarity: `True`
    meant alive). It was renamed and inverted to `is_delete` (`True` means
    soft-deleted) via a later revision, to match the naming/polarity Order's
    own soft-delete column uses.
    """

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", ondelete="RESTRICT", name="fk_products_category"),
        nullable=False,
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(11, 2), nullable=False)
    stock_quantity = db.Column(db.Integer, nullable=False)
    is_delete = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        db.CheckConstraint("price >= 0", name="products_price_check"),
        db.CheckConstraint("stock_quantity >= 0", name="products_stock_quantity_check"),
        # PostgreSQL does not automatically index foreign-key columns.
        db.Index("idx_products_category_id", "category_id"),
    )

    category = db.relationship("Category", back_populates="products")

    # Read-only: writes go through explicit inserts against order_items,
    # because quantity and unit_price are NOT NULL with no default.
    orders = db.relationship(
        "Order",
        secondary=order_items,
        back_populates="products",
        viewonly=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category_id": self.category_id,
            "name": self.name,
            "description": self.description,
            "price": float(self.price) if self.price is not None else None,
            "stock_quantity": self.stock_quantity,
            "is_delete": self.is_delete,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Product {self.id} {self.name}>"


class Order(db.Model):
    """A purchase placed by a user, linked to products through order_items.

    ``is_delete`` was added through a reviewed Flask-Migrate revision,
    following the same pattern as ``User.role`` / ``Product.is_active``. It
    backs a simple soft-delete for ``DELETE /orders/<id>``: the row is never
    physically removed, `is_delete` is set to `True` instead. Unlike the
    product soft-delete logic, this is unconditional; it does not inspect
    `status` first.
    """

    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT", name="fk_orders_user"),
        nullable=False,
    )
    total_price = db.Column(
        db.Numeric(14, 2),
        nullable=False,
        server_default=text("0"),
    )
    status = db.Column(
        db.String(75),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    is_delete = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        db.CheckConstraint("total_price >= 0", name="orders_total_price_check"),
        db.Index("idx_orders_user_id", "user_id"),
    )

    user = db.relationship("User", back_populates="orders")

    # Read-only for the same reason as Product.orders.
    products = db.relationship(
        "Product",
        secondary=order_items,
        back_populates="orders",
        viewonly=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "total_price": float(self.total_price) if self.total_price is not None else None,
            "status": self.status,
            "is_delete": self.is_delete,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Order {self.id} user={self.user_id} {self.status}>"
