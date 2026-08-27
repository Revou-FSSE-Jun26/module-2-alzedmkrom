"""Tests for the Category CRUD endpoints (`categories_bp` in routes.py).

Each endpoint gets at least one happy-path test (correct status code and
response shape for valid input) and at least one error-case test (correct
error status code and a meaningful message for invalid/missing/conflicting
input), matching the validation rules implemented in `create_category`,
`list_categories`, `get_category`, `update_category`, and `delete_category`.
"""

from extensions import db
from models import Category, Product


def _create_category(client, name="Electronics", description="Gadgets and devices"):
    """Helper: create a category through the real endpoint, return its dict."""
    resp = client.post("/categories", json={"name": name, "description": description})
    assert resp.status_code == 201
    return resp.get_json()


# ---------------------------------------------------------------------------
# POST /categories
# ---------------------------------------------------------------------------


def test_create_category_happy_path(client):
    resp = client.post(
        "/categories",
        json={"name": "Electronics", "description": "Gadgets and devices"},
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"] is not None
    assert body["name"] == "Electronics"
    assert body["description"] == "Gadgets and devices"


def test_create_category_without_description_happy_path(client):
    """description is optional and unvalidated per the route's docstring."""
    resp = client.post("/categories", json={"name": "Stationery"})

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Stationery"
    assert body["description"] is None


def test_create_category_missing_body_error(client):
    resp = client.post(
        "/categories",
        data="not json",
        content_type="text/plain",
    )

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_create_category_blank_name_error(client):
    resp = client.post("/categories", json={"name": "   "})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Bad Request"
    assert "name" in body["message"]


def test_create_category_oversized_name_error(client):
    resp = client.post("/categories", json={"name": "x" * 256})

    assert resp.status_code == 400
    assert "255" in resp.get_json()["message"]


def test_create_category_duplicate_name_error(client):
    _create_category(client, name="Electronics")

    resp = client.post("/categories", json={"name": "Electronics"})

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "Conflict"
    assert "already exists" in body["message"]


# ---------------------------------------------------------------------------
# GET /categories
# ---------------------------------------------------------------------------


def test_list_categories_happy_path(client):
    _create_category(client, name="Electronics")
    _create_category(client, name="Apparel", description="Clothes")

    resp = client.get("/categories")

    assert resp.status_code == 200
    names = {category["name"] for category in resp.get_json()}
    assert names == {"Electronics", "Apparel"}


def test_list_categories_empty_is_not_an_error(client):
    """No categories yet is a valid state, not an error: 200 with an empty list."""
    resp = client.get("/categories")

    assert resp.status_code == 200
    assert resp.get_json() == []


# ---------------------------------------------------------------------------
# GET /categories/<id>
# ---------------------------------------------------------------------------


def test_get_category_happy_path(client):
    created = _create_category(client, name="Electronics")

    resp = client.get(f"/categories/{created['id']}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == created["id"]
    assert body["name"] == "Electronics"
    assert body["products"] == []


def test_get_category_includes_its_products(client, app):
    created = _create_category(client, name="Electronics")

    with app.app_context():
        product = Product(
            category_id=created["id"],
            name="USB Cable",
            price=15000,
            stock_quantity=10,
        )
        db.session.add(product)
        db.session.commit()

    resp = client.get(f"/categories/{created['id']}")

    assert resp.status_code == 200
    products = resp.get_json()["products"]
    assert len(products) == 1
    assert products[0]["name"] == "USB Cable"


def test_get_category_not_found_error(client):
    resp = client.get("/categories/999")

    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"
    assert "999" in body["message"]


# ---------------------------------------------------------------------------
# PUT /categories/<id>
# ---------------------------------------------------------------------------


def test_update_category_happy_path(client):
    created = _create_category(client, name="Electronics", description="Old")

    resp = client.put(
        f"/categories/{created['id']}",
        json={"name": "Consumer Electronics", "description": "New"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "Consumer Electronics"
    assert body["description"] == "New"


def test_update_category_partial_update_leaves_other_field_untouched(client):
    created = _create_category(client, name="Electronics", description="Original")

    resp = client.put(f"/categories/{created['id']}", json={"description": "Updated"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "Electronics"
    assert body["description"] == "Updated"


def test_update_category_not_found_error(client):
    resp = client.put("/categories/999", json={"name": "Anything"})

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


def test_update_category_blank_name_error(client):
    created = _create_category(client, name="Electronics")

    resp = client.put(f"/categories/{created['id']}", json={"name": ""})

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bad Request"


def test_update_category_duplicate_name_error(client):
    _create_category(client, name="Electronics")
    other = _create_category(client, name="Apparel")

    resp = client.put(f"/categories/{other['id']}", json={"name": "Electronics"})

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "Conflict"


# ---------------------------------------------------------------------------
# DELETE /categories/<id>
# ---------------------------------------------------------------------------


def test_delete_category_happy_path(client):
    created = _create_category(client, name="Electronics")

    resp = client.delete(f"/categories/{created['id']}")

    assert resp.status_code == 200
    assert str(created["id"]) in resp.get_json()["message"]

    # Confirms it is actually gone, not just a 200 with no effect.
    follow_up = client.get(f"/categories/{created['id']}")
    assert follow_up.status_code == 404


def test_delete_category_not_found_error(client):
    resp = client.delete("/categories/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not Found"


def test_delete_category_blocked_by_products_error(client, app):
    created = _create_category(client, name="Electronics")

    with app.app_context():
        product = Product(
            category_id=created["id"],
            name="USB Cable",
            price=15000,
            stock_quantity=10,
        )
        db.session.add(product)
        db.session.commit()

    resp = client.delete(f"/categories/{created['id']}")

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "Conflict"
    assert "products" in body["message"]

    # Confirms the category was NOT removed by the failed attempt.
    still_there = client.get(f"/categories/{created['id']}")
    assert still_there.status_code == 200
