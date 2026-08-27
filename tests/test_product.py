"""Tests for the Product CRUD endpoints (`products_bp` in routes.py).

Covers happy path and error cases for GET (list + by id), POST, PUT, and
DELETE, including the three-way delete outcome (blocked / hard-delete /
soft-delete) driven by the referencing orders' status.
"""

from decimal import Decimal

from extensions import db
from models import Category, Order, Product, User, order_items


def _create_category(app, name="Electronics"):
    with app.app_context():
        category = Category(name=name)
        db.session.add(category)
        db.session.commit()
        return category.id


def _create_product(client, category_id, name="USB Cable", price=15000, stock_quantity=10):
    resp = client.post(
        "/products",
        json={
            "category_id": category_id,
            "name": name,
            "price": price,
            "stock_quantity": stock_quantity,
        },
    )
    assert resp.status_code == 201
    return resp.get_json()


def _attach_order(app, product_id, status="PENDING", quantity=1, unit_price=Decimal("100")):
    """Insert a user + order + order_items row referencing `product_id`
    directly, bypassing the /orders and /users routes (out of scope for this
    file). A real user row is required: `orders.user_id` is a foreign key,
    and the test DB enforces it (see conftest.py's PRAGMA foreign_keys=ON)."""
    with app.app_context():
        user = User(username=f"buyer{product_id}", email=f"buyer{product_id}@example.com")
        user.set_password("hunter2")
        db.session.add(user)
        db.session.flush()

        order = Order(user_id=user.id, status=status, total_price=unit_price * quantity)
        db.session.add(order)
        db.session.flush()
        db.session.execute(
            order_items.insert().values(
                order_id=order.id,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
        db.session.commit()
        return order.id


# ---------------------------------------------------------------------------
# POST /products
# ---------------------------------------------------------------------------


def test_create_product_happy_path(client, app):
    category_id = _create_category(app)

    resp = client.post(
        "/products",
        json={
            "category_id": category_id,
            "name": "USB Cable",
            "price": 15000,
            "stock_quantity": 10,
        },
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "USB Cable"
    assert body["price"] == 15000.0
    assert body["is_delete"] is False


def test_create_product_missing_body_error(client):
    resp = client.post("/products", data="not json", content_type="text/plain")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_create_product_missing_required_field_error(client, app):
    category_id = _create_category(app)

    resp = client.post("/products", json={"category_id": category_id, "name": "USB Cable"})

    assert resp.status_code == 400
    assert "price" in resp.get_json()["message"]


def test_create_product_unknown_category_error(client):
    resp = client.post(
        "/products",
        json={"category_id": 999, "name": "USB Cable", "price": 100, "stock_quantity": 1},
    )

    assert resp.status_code == 400
    assert "999" in resp.get_json()["message"]


def test_create_product_negative_price_error(client, app):
    category_id = _create_category(app)

    resp = client.post(
        "/products",
        json={"category_id": category_id, "name": "USB Cable", "price": -5, "stock_quantity": 1},
    )

    assert resp.status_code == 400
    assert "price" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# GET /products
# ---------------------------------------------------------------------------


def test_list_products_happy_path(client, app):
    category_id = _create_category(app)
    _create_product(client, category_id, name="USB Cable")
    _create_product(client, category_id, name="HDMI Cable")

    resp = client.get("/products")

    assert resp.status_code == 200
    names = {product["name"] for product in resp.get_json()}
    assert names == {"USB Cable", "HDMI Cable"}


def test_list_products_excludes_soft_deleted_by_default(client, app):
    category_id = _create_category(app)
    product = _create_product(client, category_id, name="Discontinued Item")
    with app.app_context():
        db.session.get(Product, product["id"]).is_delete = True
        db.session.commit()

    resp = client.get("/products")
    assert resp.get_json() == []

    resp_all = client.get("/products?include_deleted=true")
    assert len(resp_all.get_json()) == 1


# ---------------------------------------------------------------------------
# GET /products/<id>
# ---------------------------------------------------------------------------


def test_get_product_happy_path(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)

    resp = client.get(f"/products/{created['id']}")

    assert resp.status_code == 200
    assert resp.get_json()["name"] == "USB Cable"


def test_get_product_not_found_error(client):
    resp = client.get("/products/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


# ---------------------------------------------------------------------------
# PUT /products/<id>
# ---------------------------------------------------------------------------


def test_update_product_happy_path(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)

    resp = client.put(f"/products/{created['id']}", json={"stock_quantity": 42})

    assert resp.status_code == 200
    assert resp.get_json()["stock_quantity"] == 42


def test_update_product_not_found_error(client):
    resp = client.put("/products/999", json={"stock_quantity": 5})

    assert resp.status_code == 404


def test_update_product_negative_stock_error(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)

    resp = client.put(f"/products/{created['id']}", json={"stock_quantity": -1})

    assert resp.status_code == 422


def test_update_product_unknown_category_error(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)

    resp = client.put(f"/products/{created['id']}", json={"category_id": 999})

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /products/<id>
# ---------------------------------------------------------------------------


def test_delete_product_never_ordered_hard_deletes(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)

    resp = client.delete(f"/products/{created['id']}")

    assert resp.status_code == 200
    assert "deleted successfully" in resp.get_json()["message"]

    follow_up = client.get(f"/products/{created['id']}")
    assert follow_up.status_code == 404


def test_delete_product_not_found_error(client):
    resp = client.delete("/products/999")

    assert resp.status_code == 404


def test_delete_product_blocked_by_active_order_error(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)
    _attach_order(app, created["id"], status="PENDING")

    resp = client.delete(f"/products/{created['id']}")

    assert resp.status_code == 409
    assert "active orders" in resp.get_json()["message"]

    # The product must still exist and still be active.
    with app.app_context():
        product = db.session.get(Product, created["id"])
        assert product is not None
        assert product.is_delete is False


def test_delete_product_only_finalized_orders_soft_deletes(client, app):
    category_id = _create_category(app)
    created = _create_product(client, category_id)
    _attach_order(app, created["id"], status="COMPLETED")

    resp = client.delete(f"/products/{created['id']}")

    assert resp.status_code == 200
    assert "soft-deleted" in resp.get_json()["message"]

    with app.app_context():
        product = db.session.get(Product, created["id"])
        assert product is not None
        assert product.is_delete is True
