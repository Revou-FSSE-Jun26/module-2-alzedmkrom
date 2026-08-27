"""Tests for the Order GET/PUT/DELETE endpoints (`orders_bp` in routes.py).

`create_order` (POST /orders) is exercised here only as setup for these
tests; its own dedicated validation/stock-deduction coverage lives in
test_create_order.py.
"""

from extensions import db
from models import Category, Product, User


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


def _create_order(client, user_id, product_id, quantity=1):
    resp = client.post(
        "/orders",
        json={"user_id": user_id, "items": [{"product_id": product_id, "quantity": quantity}]},
    )
    assert resp.status_code == 201
    return resp.get_json()


# ---------------------------------------------------------------------------
# GET /orders
# ---------------------------------------------------------------------------


def test_list_orders_happy_path(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)

    resp = client.get(f"/orders?user_id={user_id}")

    assert resp.status_code == 200
    orders = resp.get_json()
    assert len(orders) == 1
    assert orders[0]["id"] == created["id"]


def test_list_orders_excludes_soft_deleted_by_default(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)
    client.delete(f"/orders/{created['id']}")

    resp = client.get(f"/orders?user_id={user_id}")
    assert resp.get_json() == []

    resp_all = client.get(f"/orders?user_id={user_id}&include_deleted=true")
    assert len(resp_all.get_json()) == 1


def test_list_orders_missing_user_id_error(client):
    resp = client.get("/orders")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_list_orders_unknown_user_error(client):
    resp = client.get("/orders?user_id=999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


# ---------------------------------------------------------------------------
# GET /orders/<id>
# ---------------------------------------------------------------------------


def test_get_order_happy_path(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app, price=15000)
    created = _create_order(client, user_id, product_id, quantity=2)

    resp = client.get(f"/orders/{created['id']}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == created["id"]
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 2
    assert body["items"][0]["product"]["id"] == product_id


def test_get_order_not_found_error(client):
    resp = client.get("/orders/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


def test_get_order_returns_even_when_soft_deleted(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)
    client.delete(f"/orders/{created['id']}")

    resp = client.get(f"/orders/{created['id']}")

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PUT /orders/<id>
# ---------------------------------------------------------------------------


def test_update_order_status_happy_path(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)

    resp = client.put(f"/orders/{created['id']}", json={"status": "processing"})

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "PROCESSING"


def test_update_order_status_not_found_error(client):
    resp = client.put("/orders/999", json={"status": "PROCESSING"})

    assert resp.status_code == 404


def test_update_order_status_blank_status_error(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)

    resp = client.put(f"/orders/{created['id']}", json={"status": "   "})

    assert resp.status_code == 400


def test_update_order_status_locked_after_finalized_error(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)
    client.put(f"/orders/{created['id']}", json={"status": "COMPLETED"})

    resp = client.put(f"/orders/{created['id']}", json={"status": "PROCESSING"})

    assert resp.status_code == 409
    assert "COMPLETED" in resp.get_json()["message"]


def test_update_order_status_cancelled_restores_stock(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app, stock_quantity=10)
    created = _create_order(client, user_id, product_id, quantity=3)

    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7

    resp = client.put(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 10


def test_update_order_status_completed_does_not_restore_stock(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app, stock_quantity=10)
    created = _create_order(client, user_id, product_id, quantity=3)

    client.put(f"/orders/{created['id']}", json={"status": "COMPLETED"})

    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7


# ---------------------------------------------------------------------------
# DELETE /orders/<id>
# ---------------------------------------------------------------------------


def test_delete_order_happy_path(client, app):
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)

    resp = client.delete(f"/orders/{created['id']}")

    assert resp.status_code == 200
    assert str(created["id"]) in resp.get_json()["message"]

    with app.app_context():
        from models import Order
        order = db.session.get(Order, created["id"])
        assert order is not None  # soft delete: row still exists
        assert order.is_delete is True


def test_delete_order_not_found_error(client):
    resp = client.delete("/orders/999")

    assert resp.status_code == 404


def test_delete_order_works_even_on_active_status(client, app):
    """delete_order has no status check, unlike delete_product."""
    user_id = _create_user(client)
    product_id = _create_product(app)
    created = _create_order(client, user_id, product_id)
    client.put(f"/orders/{created['id']}", json={"status": "PROCESSING"})

    resp = client.delete(f"/orders/{created['id']}")

    assert resp.status_code == 200
