"""Tests for the Product CRUD endpoints (`products_bp` in routes.py).

Covers happy path and error cases for GET (list + by id), POST, PUT, and
DELETE, including the three-way delete outcome (blocked / hard-delete /
soft-delete) driven by the referencing orders' status.

Reads are public, so they use the anonymous `client`. Writes are admin-only,
so they use `admin_client`; the validation-error tests use it too, since
without a token they would stop at 401 and never reach the validation being
tested. Authorization itself is covered by the last section.
"""

from decimal import Decimal

import pytest

from extensions import db
from models import Category, Order, Product, User, order_items


def _create_category(app, name="Electronics"):
    with app.app_context():
        category = Category(name=name)
        db.session.add(category)
        db.session.commit()
        return category.id


def _create_product(admin_client, category_id, name="USB Cable", price=15000, stock_quantity=10):
    resp = admin_client.post(
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
        user.set_password("hunter2pass")
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


def test_create_product_happy_path(admin_client, app):
    category_id = _create_category(app)

    resp = admin_client.post(
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


def test_create_product_missing_body_error(admin_client):
    resp = admin_client.post("/products", data="not json", content_type="text/plain")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_create_product_missing_required_field_error(admin_client, app):
    category_id = _create_category(app)

    resp = admin_client.post("/products", json={"category_id": category_id, "name": "USB Cable"})

    assert resp.status_code == 400
    assert "price" in resp.get_json()["message"]


def test_create_product_unknown_category_error(admin_client):
    resp = admin_client.post(
        "/products",
        json={"category_id": 999, "name": "USB Cable", "price": 100, "stock_quantity": 1},
    )

    assert resp.status_code == 400
    assert "999" in resp.get_json()["message"]


def test_create_product_negative_price_error(admin_client, app):
    category_id = _create_category(app)

    resp = admin_client.post(
        "/products",
        json={"category_id": category_id, "name": "USB Cable", "price": -5, "stock_quantity": 1},
    )

    assert resp.status_code == 400
    assert "price" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# GET /products  (public)
# ---------------------------------------------------------------------------


def test_list_products_happy_path(client, admin_client, app):
    category_id = _create_category(app)
    _create_product(admin_client, category_id, name="USB Cable")
    _create_product(admin_client, category_id, name="HDMI Cable")

    resp = client.get("/products")

    assert resp.status_code == 200
    names = {product["name"] for product in resp.get_json()}
    assert names == {"USB Cable", "HDMI Cable"}


def test_list_products_excludes_soft_deleted_by_default(client, admin_client, app):
    category_id = _create_category(app)
    product = _create_product(admin_client, category_id, name="Discontinued Item")
    with app.app_context():
        db.session.get(Product, product["id"]).is_delete = True
        db.session.commit()

    resp = client.get("/products")
    assert resp.get_json() == []

    # include_deleted is an admin view.
    resp_all = admin_client.get("/products?include_deleted=true")
    assert len(resp_all.get_json()) == 1


def test_list_products_include_deleted_ignored_for_anonymous(client, admin_client, app):
    """A non-admin asking for soft-deleted rows gets the normal public list."""
    category_id = _create_category(app)
    product = _create_product(admin_client, category_id, name="Discontinued Item")
    with app.app_context():
        db.session.get(Product, product["id"]).is_delete = True
        db.session.commit()

    resp = client.get("/products?include_deleted=true")

    assert resp.status_code == 200
    assert resp.get_json() == []


def test_list_products_include_deleted_ignored_for_customer(customer_client, admin_client, app):
    category_id = _create_category(app)
    product = _create_product(admin_client, category_id, name="Discontinued Item")
    with app.app_context():
        db.session.get(Product, product["id"]).is_delete = True
        db.session.commit()

    resp = customer_client.get("/products?include_deleted=true")

    assert resp.status_code == 200
    assert resp.get_json() == []


# ---------------------------------------------------------------------------
# GET /products/<id>  (public)
# ---------------------------------------------------------------------------


def test_get_product_happy_path(client, admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

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


def test_update_product_happy_path(admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

    resp = admin_client.put(f"/products/{created['id']}", json={"stock_quantity": 42})

    assert resp.status_code == 200
    assert resp.get_json()["stock_quantity"] == 42


def test_update_product_not_found_error(admin_client):
    resp = admin_client.put("/products/999", json={"stock_quantity": 5})

    assert resp.status_code == 404


def test_update_product_negative_stock_error(admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

    resp = admin_client.put(f"/products/{created['id']}", json={"stock_quantity": -1})

    assert resp.status_code == 422


def test_update_product_unknown_category_error(admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

    resp = admin_client.put(f"/products/{created['id']}", json={"category_id": 999})

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /products/<id>
# ---------------------------------------------------------------------------


def test_delete_product_never_ordered_hard_deletes(client, admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

    resp = admin_client.delete(f"/products/{created['id']}")

    assert resp.status_code == 200
    assert "deleted successfully" in resp.get_json()["message"]

    follow_up = client.get(f"/products/{created['id']}")
    assert follow_up.status_code == 404


def test_delete_product_not_found_error(admin_client):
    resp = admin_client.delete("/products/999")

    assert resp.status_code == 404


def test_delete_product_blocked_by_active_order_error(admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)
    _attach_order(app, created["id"], status="PENDING")

    resp = admin_client.delete(f"/products/{created['id']}")

    assert resp.status_code == 409
    assert "active orders" in resp.get_json()["message"]

    # The product must still exist and still be active.
    with app.app_context():
        product = db.session.get(Product, created["id"])
        assert product is not None
        assert product.is_delete is False


def test_delete_product_only_finalized_orders_soft_deletes(admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)
    _attach_order(app, created["id"], status="COMPLETED")

    resp = admin_client.delete(f"/products/{created['id']}")

    assert resp.status_code == 200
    assert "soft-deleted" in resp.get_json()["message"]

    with app.app_context():
        product = db.session.get(Product, created["id"])
        assert product is not None
        assert product.is_delete is True


# ---------------------------------------------------------------------------
# Authorization on the write endpoints
# ---------------------------------------------------------------------------


def test_create_product_requires_token(client, app):
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

    assert resp.status_code == 401
    assert resp.get_json()["code"] == "authorization_required"


def test_create_product_forbidden_for_customer(customer_client, app):
    category_id = _create_category(app)

    resp = customer_client.post(
        "/products",
        json={
            "category_id": category_id,
            "name": "USB Cable",
            "price": 15000,
            "stock_quantity": 10,
        },
    )

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "admin_required"


def test_update_product_forbidden_for_customer(customer_client, admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

    resp = customer_client.put(f"/products/{created['id']}", json={"stock_quantity": 1})

    assert resp.status_code == 403


def test_delete_product_forbidden_for_customer(customer_client, admin_client, app):
    category_id = _create_category(app)
    created = _create_product(admin_client, category_id)

    resp = customer_client.delete(f"/products/{created['id']}")

    assert resp.status_code == 403

    # Nothing was removed.
    with app.app_context():
        assert db.session.get(Product, created["id"]) is not None


def test_write_endpoints_reject_malformed_token(client, app):
    category_id = _create_category(app)

    resp = client.post(
        "/products",
        json={
            "category_id": category_id,
            "name": "USB Cable",
            "price": 15000,
            "stock_quantity": 10,
        },
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert resp.status_code == 422 or resp.status_code == 401
    assert resp.get_json()["code"] in {"token_invalid", "authorization_required"}


# ---------------------------------------------------------------------------
# GET /products filtering: ?search= and ?category_id=
# ---------------------------------------------------------------------------


def _catalogue(app, admin_client):
    """Two categories with distinguishable products, for the filter tests."""
    electronics = _create_category(app, name="Electronics")
    apparel = _create_category(app, name="Apparel")

    _create_product(admin_client, electronics, name="Smart Watch")
    _create_product(admin_client, electronics, name="USB Cable")
    _create_product(admin_client, apparel, name="Rain Jacket")

    # A product whose *description* is the only place the term appears, so the
    # tests can tell a name-only search from one that covers both.
    resp = admin_client.post(
        "/products",
        json={
            "category_id": apparel,
            "name": "Fitness Band",
            "description": "Pairs with any smart watch",
            "price": 200000,
            "stock_quantity": 5,
        },
    )
    assert resp.status_code == 201

    return {"electronics": electronics, "apparel": apparel}


def _names(resp):
    return sorted(product["name"] for product in resp.get_json())


# -- ?search= ---------------------------------------------------------------


def test_search_matches_a_product_name(client, admin_client, app):
    _catalogue(app, admin_client)

    resp = client.get("/products?search=jacket")

    assert resp.status_code == 200
    assert _names(resp) == ["Rain Jacket"]


def test_search_is_case_insensitive(client, admin_client, app):
    _catalogue(app, admin_client)

    for term in ("JACKET", "Jacket", "jAcKeT"):
        assert _names(client.get(f"/products?search={term}")) == ["Rain Jacket"]


def test_search_matches_a_partial_word(client, admin_client, app):
    _catalogue(app, admin_client)

    resp = client.get("/products?search=cab")

    assert _names(resp) == ["USB Cable"]


def test_search_also_matches_the_description(client, admin_client, app):
    """'watch' appears in one name and one description; both come back."""
    _catalogue(app, admin_client)

    resp = client.get("/products?search=watch")

    assert _names(resp) == ["Fitness Band", "Smart Watch"]


def test_search_with_no_matches_returns_an_empty_list(client, admin_client, app):
    _catalogue(app, admin_client)

    resp = client.get("/products?search=nothinglikethis")

    assert resp.status_code == 200
    assert resp.get_json() == []


def test_blank_search_returns_everything(client, admin_client, app):
    """Clearing a search box need not mean dropping the parameter."""
    _catalogue(app, admin_client)

    resp = client.get("/products?search=")

    assert resp.status_code == 200
    assert len(resp.get_json()) == 4


def test_search_is_trimmed(client, admin_client, app):
    _catalogue(app, admin_client)

    assert _names(client.get("/products?search=%20%20jacket%20%20")) == ["Rain Jacket"]


def test_search_excludes_soft_deleted_products(client, admin_client, app):
    _catalogue(app, admin_client)
    with app.app_context():
        product = (
            db.session.query(Product).filter(Product.name == "Rain Jacket").one()
        )
        product.is_delete = True
        db.session.commit()

    assert client.get("/products?search=jacket").get_json() == []


# -- LIKE wildcards must not leak out of the search term --------------------


def test_search_percent_is_not_a_wildcard(client, admin_client, app):
    """A bare '%' would match every row if it reached the query unescaped."""
    _catalogue(app, admin_client)

    resp = client.get("/products?search=%25")  # url-encoded %

    assert resp.status_code == 200
    assert resp.get_json() == []


def test_search_underscore_is_not_a_wildcard(client, admin_client, app):
    """'_' matches any single character in LIKE; here it must be literal."""
    _catalogue(app, admin_client)

    # Would match "Smart Watch" if '_' were still a wildcard.
    resp = client.get("/products?search=s_art")

    assert resp.get_json() == []


def test_search_backslash_is_literal(client, admin_client, app):
    _catalogue(app, admin_client)

    resp = client.get("/products?search=%5C")  # url-encoded backslash

    assert resp.status_code == 200
    assert resp.get_json() == []


def test_search_term_too_long_is_rejected(client, admin_client, app):
    _catalogue(app, admin_client)

    resp = client.get("/products?search=" + ("x" * 256))

    assert resp.status_code == 400
    assert "search" in resp.get_json()["message"]


# -- ?category_id= ----------------------------------------------------------


def test_category_id_filters_the_listing(client, admin_client, app):
    ids = _catalogue(app, admin_client)

    resp = client.get(f"/products?category_id={ids['electronics']}")

    assert resp.status_code == 200
    assert _names(resp) == ["Smart Watch", "USB Cable"]


def test_category_id_returns_only_that_category(client, admin_client, app):
    """Regression: the filter used to be ignored, returning everything."""
    ids = _catalogue(app, admin_client)

    resp = client.get(f"/products?category_id={ids['apparel']}")

    returned = resp.get_json()
    assert _names(resp) == ["Fitness Band", "Rain Jacket"]
    assert {p["category_id"] for p in returned} == {ids["apparel"]}


def test_unknown_category_id_returns_an_empty_list(client, admin_client, app):
    """A filter matching nothing is a valid answer, not a 404."""
    _catalogue(app, admin_client)

    resp = client.get("/products?category_id=999999")

    assert resp.status_code == 200
    assert resp.get_json() == []


@pytest.mark.parametrize(
    "value", ["abc", "-1", "0", "1.5", "1;DROP TABLE", "undefined", "null"]
)
def test_invalid_category_id_is_rejected(client, admin_client, app, value):
    _catalogue(app, admin_client)

    resp = client.get(f"/products?category_id={value}")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"
    assert "category_id" in resp.get_json()["message"]


def test_blank_category_id_returns_everything(client, admin_client, app):
    """A cleared dropdown sends `?category_id=`; that must not be an error."""
    _catalogue(app, admin_client)

    resp = client.get("/products?category_id=")

    assert resp.status_code == 200
    assert len(resp.get_json()) == 4


# -- combined ---------------------------------------------------------------


def test_search_and_category_id_are_combined_with_and(client, admin_client, app):
    ids = _catalogue(app, admin_client)

    # "watch" alone matches Smart Watch (Electronics) and Fitness Band (Apparel).
    both = client.get(f"/products?search=watch&category_id={ids['electronics']}")

    assert _names(both) == ["Smart Watch"]


def test_filters_combine_with_include_deleted_for_an_admin(admin_client, app):
    ids = _catalogue(app, admin_client)
    with app.app_context():
        product = (
            db.session.query(Product).filter(Product.name == "Rain Jacket").one()
        )
        product.is_delete = True
        db.session.commit()

    hidden = admin_client.get(f"/products?category_id={ids['apparel']}")
    shown = admin_client.get(
        f"/products?category_id={ids['apparel']}&include_deleted=true"
    )

    assert _names(hidden) == ["Fitness Band"]
    assert _names(shown) == ["Fitness Band", "Rain Jacket"]
