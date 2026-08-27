"""Dedicated tests for POST /orders (`create_order` in routes.py): its
validation chain, all-or-nothing item checks, stock deduction, and
total_price calculation.
"""

from extensions import db
from models import Category, Product


def _create_user(client, username="alice", email="alice@example.com"):
    resp = client.post("/users", json={"username": username, "email": email, "password": "hunter2"})
    assert resp.status_code == 201
    return resp.get_json()["id"]


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


def test_create_order_happy_path_single_item(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app, price=15000, stock_quantity=10)

    resp = client.post(
        "/orders",
        json={"user_id": user_id, "items": [{"product_id": product_id, "quantity": 3}]},
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "PENDING"
    assert body["total_price"] == 45000.0

    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7


def test_create_order_happy_path_multiple_items_sums_total(client, app):
    user_id = _create_user(client)
    product_a = _create_product(app, name="A", price=10000, stock_quantity=5)
    product_b = _create_product(app, name="B", price=25000, stock_quantity=5)

    resp = client.post(
        "/orders",
        json={
            "user_id": user_id,
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
# Body / user_id validation
# ---------------------------------------------------------------------------


def test_create_order_missing_body_error(client):
    resp = client.post("/orders", data="not json", content_type="text/plain")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_create_order_missing_user_id_error(client, app):
    product_id = _create_product(app)

    resp = client.post("/orders", json={"items": [{"product_id": product_id, "quantity": 1}]})

    assert resp.status_code == 400
    assert "user_id" in resp.get_json()["message"]


def test_create_order_unknown_user_error(client, app):
    product_id = _create_product(app)

    resp = client.post(
        "/orders",
        json={"user_id": 999, "items": [{"product_id": product_id, "quantity": 1}]},
    )

    assert resp.status_code == 400
    assert "999" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# items validation
# ---------------------------------------------------------------------------


def test_create_order_empty_items_error(client):
    user_id = _create_user(client)

    resp = client.post("/orders", json={"user_id": user_id, "items": []})

    assert resp.status_code == 400
    assert "items" in resp.get_json()["message"]


def test_create_order_missing_items_field_error(client):
    user_id = _create_user(client)

    resp = client.post("/orders", json={"user_id": user_id})

    assert resp.status_code == 400


def test_create_order_item_missing_quantity_error(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)

    resp = client.post("/orders", json={"user_id": user_id, "items": [{"product_id": product_id}]})

    assert resp.status_code == 400
    assert "quantity" in resp.get_json()["message"]


def test_create_order_non_positive_quantity_error(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)

    resp = client.post(
        "/orders",
        json={"user_id": user_id, "items": [{"product_id": product_id, "quantity": 0}]},
    )

    assert resp.status_code == 400
    assert "greater than zero" in resp.get_json()["message"]


def test_create_order_duplicate_product_in_same_order_error(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app, stock_quantity=10)

    resp = client.post(
        "/orders",
        json={
            "user_id": user_id,
            "items": [
                {"product_id": product_id, "quantity": 1},
                {"product_id": product_id, "quantity": 2},
            ],
        },
    )

    assert resp.status_code == 400
    assert "more than once" in resp.get_json()["message"]


def test_create_order_unknown_product_error(client):
    user_id = _create_user(client)

    resp = client.post("/orders", json={"user_id": user_id, "items": [{"product_id": 999, "quantity": 1}]})

    assert resp.status_code == 400
    assert "999" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# Insufficient stock: all-or-nothing
# ---------------------------------------------------------------------------


def test_create_order_insufficient_stock_error(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app, stock_quantity=2)

    resp = client.post(
        "/orders",
        json={"user_id": user_id, "items": [{"product_id": product_id, "quantity": 5}]},
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "2 in stock" in body["message"]

    # Stock must be untouched by the rejected order.
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 2


def test_create_order_insufficient_stock_blocks_whole_order(client, app):
    """One bad item rejects the entire order; the good item's stock must
    not be partially deducted."""
    user_id = _create_user(client)
    product_ok = _create_product(app, name="OK", stock_quantity=10)
    product_short = _create_product(app, name="Short", stock_quantity=1)

    resp = client.post(
        "/orders",
        json={
            "user_id": user_id,
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
