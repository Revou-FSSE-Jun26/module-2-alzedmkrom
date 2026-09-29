"""Dedicated tests for POST /orders (`create_order` in routes.py): its
validation chain, all-or-nothing item checks, stock deduction, and
total_price calculation.

The endpoint now requires an access token and takes the order's owner from
it, so these tests place orders through `customer_client` and send only
`items`. The `user_id` body field that earlier versions required is gone;
`test_create_order_ignores_user_id_in_body` pins down that supplying one
cannot redirect the order to another account.
"""

from extensions import db
from models import Category, Order, Product


def _create_product(app, name="USB Cable", price=15000, stock_quantity=10):
    with app.app_context():
        category = Category(name=f"Category for {name}")
        db.session.add(category)
        db.session.flush()
        product = Product(category_id=category.id, name=name, price=price, stock_quantity=stock_quantity)
        db.session.add(product)
        db.session.commit()
        return product.id


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_create_order_happy_path_single_item(customer_client, customer_user, app):
    product_id = _create_product(app, price=15000, stock_quantity=10)

    resp = customer_client.post(
        "/orders",
        json={"items": [{"product_id": product_id, "quantity": 3}]},
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "PENDING"
    assert body["total_price"] == 45000.0
    assert body["user_id"] == customer_user

    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7


def test_create_order_happy_path_multiple_items_sums_total(customer_client, app):
    product_a = _create_product(app, name="A", price=10000, stock_quantity=5)
    product_b = _create_product(app, name="B", price=25000, stock_quantity=5)

    resp = customer_client.post(
        "/orders",
        json={
            "items": [
                {"product_id": product_a, "quantity": 2},
                {"product_id": product_b, "quantity": 1},
            ],
        },
    )

    assert resp.status_code == 201
    # 2 * 10000 + 1 * 25000 = 45000
    assert resp.get_json()["total_price"] == 45000.0


# ---------------------------------------------------------------------------
# Ownership comes from the token, not the body
# ---------------------------------------------------------------------------


def test_create_order_requires_token(client, app):
    product_id = _create_product(app)

    resp = client.post("/orders", json={"items": [{"product_id": product_id, "quantity": 1}]})

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "authorization_required"


def test_create_order_ignores_user_id_in_body(customer_client, customer_user, admin_user, app):
    """A `user_id` in the body must not place the order on another account."""
    product_id = _create_product(app)

    resp = customer_client.post(
        "/orders",
        json={
            "user_id": admin_user,  # someone else's id
            "items": [{"product_id": product_id, "quantity": 1}],
        },
    )

    assert resp.status_code == 201
    assert resp.get_json()["user_id"] == customer_user

    with app.app_context():
        order = db.session.get(Order, resp.get_json()["id"])
        assert order.user_id == customer_user


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------


def test_create_order_missing_body_error(customer_client):
    resp = customer_client.post("/orders", data="not json", content_type="text/plain")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


# ---------------------------------------------------------------------------
# items validation
# ---------------------------------------------------------------------------


def test_create_order_empty_items_error(customer_client):
    resp = customer_client.post("/orders", json={"items": []})

    assert resp.status_code == 400
    assert "items" in resp.get_json()["message"]


def test_create_order_missing_items_field_error(customer_client):
    resp = customer_client.post("/orders", json={})

    assert resp.status_code == 400


def test_create_order_item_missing_quantity_error(customer_client, app):
    product_id = _create_product(app)

    resp = customer_client.post("/orders", json={"items": [{"product_id": product_id}]})

    assert resp.status_code == 400
    assert "quantity" in resp.get_json()["message"]


def test_create_order_non_positive_quantity_error(customer_client, app):
    product_id = _create_product(app)

    resp = customer_client.post(
        "/orders",
        json={"items": [{"product_id": product_id, "quantity": 0}]},
    )

    assert resp.status_code == 400
    assert "greater than zero" in resp.get_json()["message"]


def test_create_order_duplicate_product_in_same_order_error(customer_client, app):
    product_id = _create_product(app, stock_quantity=10)

    resp = customer_client.post(
        "/orders",
        json={
            "items": [
                {"product_id": product_id, "quantity": 1},
                {"product_id": product_id, "quantity": 2},
            ],
        },
    )

    assert resp.status_code == 400
    assert "more than once" in resp.get_json()["message"]


def test_create_order_unknown_product_error(customer_client):
    resp = customer_client.post("/orders", json={"items": [{"product_id": 999, "quantity": 1}]})

    assert resp.status_code == 400
    assert "999" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# Insufficient stock: all-or-nothing
# ---------------------------------------------------------------------------


def test_create_order_insufficient_stock_error(customer_client, app):
    product_id = _create_product(app, stock_quantity=2)

    resp = customer_client.post(
        "/orders",
        json={"items": [{"product_id": product_id, "quantity": 5}]},
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "2 in stock" in body["message"]

    # Stock must be untouched by the rejected order.
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 2


def test_create_order_insufficient_stock_blocks_whole_order(customer_client, app):
    """One bad item rejects the entire order; the good item's stock must
    not be partially deducted."""
    product_ok = _create_product(app, name="OK", stock_quantity=10)
    product_short = _create_product(app, name="Short", stock_quantity=1)

    resp = customer_client.post(
        "/orders",
        json={
            "items": [
                {"product_id": product_ok, "quantity": 5},
                {"product_id": product_short, "quantity": 5},
            ],
        },
    )

    assert resp.status_code == 400
    with app.app_context():
        assert db.session.get(Product, product_ok).stock_quantity == 10
        assert db.session.get(Product, product_short).stock_quantity == 1
