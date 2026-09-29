"""Tests for the Order GET/PUT/DELETE endpoints (`orders_bp` in routes.py).

`create_order` (POST /orders) is exercised here only as setup for these
tests; its own dedicated validation/stock-deduction coverage lives in
test_create_order.py.

Who may do what:
  * a customer reads and soft-deletes **their own** orders
  * only an admin changes an order's `status` (it moves stock)
  * an admin may read any order, and may list another user's via ?user_id=

The last section pins those boundaries down, including that one customer
cannot reach another customer's order by guessing its id.
"""

from extensions import db
from models import Category, Order, Product, User


def _create_product(app, name="USB Cable", price=15000, stock_quantity=10):
    with app.app_context():
        category = Category(name=f"Category for {name}")
        db.session.add(category)
        db.session.flush()
        product = Product(category_id=category.id, name=name, price=price, stock_quantity=stock_quantity)
        db.session.add(product)
        db.session.commit()
        return product.id


def _create_order(customer_client, product_id, quantity=1):
    resp = customer_client.post(
        "/orders",
        json={"items": [{"product_id": product_id, "quantity": quantity}]},
    )
    assert resp.status_code == 201
    return resp.get_json()


# ---------------------------------------------------------------------------
# GET /orders
# ---------------------------------------------------------------------------


def test_list_orders_happy_path(customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = customer_client.get("/orders")

    assert resp.status_code == 200
    orders = resp.get_json()
    assert len(orders) == 1
    assert orders[0]["id"] == created["id"]


def test_list_orders_excludes_soft_deleted_by_default(customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)
    customer_client.delete(f"/orders/{created['id']}")

    resp = customer_client.get("/orders")
    assert resp.get_json() == []

    resp_all = customer_client.get("/orders?include_deleted=true")
    assert len(resp_all.get_json()) == 1


def test_list_orders_requires_token(client):
    resp = client.get("/orders")

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "authorization_required"


def test_list_orders_unknown_user_error_for_admin(admin_client):
    resp = admin_client.get("/orders?user_id=999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


def test_list_orders_non_numeric_user_id_error(admin_client):
    resp = admin_client.get("/orders?user_id=abc")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_list_orders_admin_can_read_another_users_orders(
    admin_client, customer_client, customer_user, app
):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = admin_client.get(f"/orders?user_id={customer_user}")

    assert resp.status_code == 200
    assert [order["id"] for order in resp.get_json()] == [created["id"]]


def test_list_orders_customer_cannot_read_another_users_orders(
    customer_client, admin_user
):
    resp = customer_client.get(f"/orders?user_id={admin_user}")

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "forbidden"


# ---------------------------------------------------------------------------
# GET /orders/<id>
# ---------------------------------------------------------------------------


def test_get_order_happy_path(customer_client, app):
    product_id = _create_product(app, price=15000)
    created = _create_order(customer_client, product_id, quantity=2)

    resp = customer_client.get(f"/orders/{created['id']}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == created["id"]
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 2
    assert body["items"][0]["product"]["id"] == product_id


def test_get_order_not_found_error(customer_client):
    resp = customer_client.get("/orders/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


def test_get_order_returns_even_when_soft_deleted(customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)
    customer_client.delete(f"/orders/{created['id']}")

    resp = customer_client.get(f"/orders/{created['id']}")

    assert resp.status_code == 200


def test_get_order_requires_token(client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = client.get(f"/orders/{created['id']}")

    assert resp.status_code == 401


def test_get_order_forbidden_for_other_customer(
    customer_client, authorized_client_for, make_user, app
):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    intruder_id = make_user(username="intruder", email="intruder@example.com")
    intruder = authorized_client_for(intruder_id)

    resp = intruder.get(f"/orders/{created['id']}")

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "forbidden"


def test_get_order_allowed_for_admin(admin_client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = admin_client.get(f"/orders/{created['id']}")

    assert resp.status_code == 200
    assert resp.get_json()["id"] == created["id"]


# ---------------------------------------------------------------------------
# PUT /orders/<id>  (admin only)
# ---------------------------------------------------------------------------


def test_update_order_status_happy_path(admin_client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = admin_client.put(f"/orders/{created['id']}", json={"status": "processing"})

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "PROCESSING"


def test_update_order_status_not_found_error(admin_client):
    resp = admin_client.put("/orders/999", json={"status": "PROCESSING"})

    assert resp.status_code == 404


def test_update_order_status_blank_status_error(admin_client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = admin_client.put(f"/orders/{created['id']}", json={"status": "   "})

    assert resp.status_code == 400


def test_update_order_status_locked_after_finalized_error(admin_client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)
    admin_client.put(f"/orders/{created['id']}", json={"status": "COMPLETED"})

    resp = admin_client.put(f"/orders/{created['id']}", json={"status": "PROCESSING"})

    assert resp.status_code == 409
    assert "COMPLETED" in resp.get_json()["message"]


def test_update_order_status_cancelled_restores_stock(admin_client, customer_client, app):
    product_id = _create_product(app, stock_quantity=10)
    created = _create_order(customer_client, product_id, quantity=3)

    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7

    resp = admin_client.put(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 10


def test_update_order_status_completed_does_not_restore_stock(admin_client, customer_client, app):
    product_id = _create_product(app, stock_quantity=10)
    created = _create_order(customer_client, product_id, quantity=3)

    admin_client.put(f"/orders/{created['id']}", json={"status": "COMPLETED"})

    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7


def test_update_order_status_forbidden_for_owning_customer(customer_client, app):
    """Even the order's owner cannot change its status: it moves stock."""
    product_id = _create_product(app, stock_quantity=10)
    created = _create_order(customer_client, product_id, quantity=3)

    resp = customer_client.put(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "admin_required"

    # Stock must not have been handed back.
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 7


def test_update_order_status_requires_token(client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = client.put(f"/orders/{created['id']}", json={"status": "PROCESSING"})

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /orders/<id>
# ---------------------------------------------------------------------------


def test_delete_order_happy_path(customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = customer_client.delete(f"/orders/{created['id']}")

    assert resp.status_code == 200
    assert str(created["id"]) in resp.get_json()["message"]

    with app.app_context():
        order = db.session.get(Order, created["id"])
        assert order is not None  # soft delete: row still exists
        assert order.is_delete is True


def test_delete_order_not_found_error(customer_client):
    resp = customer_client.delete("/orders/999")

    assert resp.status_code == 404


def test_delete_order_works_even_on_active_status(admin_client, customer_client, app):
    """delete_order has no status check, unlike delete_product."""
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)
    admin_client.put(f"/orders/{created['id']}", json={"status": "PROCESSING"})

    resp = customer_client.delete(f"/orders/{created['id']}")

    assert resp.status_code == 200


def test_delete_order_forbidden_for_other_customer(
    customer_client, authorized_client_for, make_user, app
):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    intruder_id = make_user(username="intruder", email="intruder@example.com")
    intruder = authorized_client_for(intruder_id)

    resp = intruder.delete(f"/orders/{created['id']}")

    assert resp.status_code == 403

    with app.app_context():
        assert db.session.get(Order, created["id"]).is_delete is False


def test_delete_order_allowed_for_admin(admin_client, customer_client, app):
    product_id = _create_product(app)
    created = _create_order(customer_client, product_id)

    resp = admin_client.delete(f"/orders/{created['id']}")

    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Order, created["id"]).is_delete is True
