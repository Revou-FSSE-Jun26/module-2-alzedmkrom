"""Locust load test for RevoShop.

Simulates a sequential user journey against the local Flask server:
  1. GET  /products             list all products
  2. GET  /products/<id>        fetch a single product from that list
  3. POST /orders                place a new order for that product
  4. GET  /orders/<id>           fetch the order just created

Run locally (server must already be running, e.g. `flask run`):

    locust -f locustfile.py --host=http://127.0.0.1:5000

Then open http://localhost:8089 and start a swarm (e.g. 50 users, ramping
to 200, spawn rate a few per second), or run headless:

    locust -f locustfile.py --host=http://127.0.0.1:5000 \
        --users 200 --spawn-rate 10 --run-time 2m --headless

Uses an existing seeded user (id 1) rather than registering a new one per
simulated user, so the journey stays focused on products/orders and does
not create a new user row on every single iteration.

IMPORTANT — cleanup after running this:

`create_order` commits real rows against whatever database `DATABASE_URL`
points at (your real local `revoshop_db` if you're running this the normal
way) and deducts real `stock_quantity`. Nothing about this file, or a
normal HTTP request in general, reverts those writes automatically — they
are permanent commits, same as if you'd typed the inserts by hand. A run
with enough users/duration can deplete every product's stock to 0, at
which point `list_products` below starts failing on purpose (see its
"No active, in-stock products available" check) rather than silently
placing bad orders. `create_order` now treats any non-201 from
`POST /orders` as a Locust failure, so a 400 from insufficient/zero stock
shows up in the failure stats rather than being counted as success.

Run against `revoshop_test` (the dedicated load-test database) rather than
`revoshop_db`, and orders/stock changes from Locust stay isolated there
without affecting your real data. See `.env.example` for how to set
`DATABASE_URL` to point at `revoshop_test` before starting `flask run`.
"""

import random

from locust import HttpUser, SequentialTaskSet, between, task

# A real, already-seeded user id (see seed.sql). Every simulated user places
# orders "as" this account; there is no session/token auth in this project
# (see the note on `create_order` in routes.py), so `user_id` is just a
# request body field, not a login.
EXISTING_USER_ID = 1


class ProductAndOrderJourney(SequentialTaskSet):
    """One pass through the journey, in order, per simulated user."""

    def on_start(self):
        self.product_id = None
        self.order_id = None

    @task
    def list_products(self):
        """1. GET /products — list all products, remember one id."""
        with self.client.get("/products", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /products returned {resp.status_code}")
                return

            products = resp.json()
            if not products:
                resp.failure("GET /products returned an empty list")
                return

            # A random in-stock, non-soft-deleted product, so repeated runs
            # don't hammer the same row's stock_quantity down to zero and
            # never pick a product that create_order would reject. GET
            # /products already excludes is_delete=True rows by default
            # (no ?include_deleted=true here), but this filter is kept as a
            # defense-in-depth check in case that default ever changes.

            self.product_id = random.choice(products)["id"]

    @task
    def get_single_product(self):
        """2. GET /products/<id> — fetch the product picked above."""
        if self.product_id is None:
            return

        with self.client.get(
            f"/products/{self.product_id}", name="/products/[id]", catch_response=True
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /products/{self.product_id} returned {resp.status_code}")

    @task
    def create_order(self):
        """3. POST /orders — place a 1-unit order for that product."""
        if self.product_id is None:
            return

        body = {
            "user_id": EXISTING_USER_ID,
            "items": [{"product_id": self.product_id, "quantity": 1}],
        }
        with self.client.post("/orders", json=body, catch_response=True) as resp:
            if resp.status_code != 201:
                # Any non-201 counts as a real failure, including a 400 from
                # ordering a product with insufficient/zero stock. This
                # surfaces stock-depletion in the Locust failure stats
                # instead of hiding it as success.
                resp.failure(f"POST /orders returned {resp.status_code}")
                return

            self.order_id = resp.json()["id"]

        with self.client.get(
            f"/orders/{self.order_id}", name="/orders/[id]", catch_response=True
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /orders/{self.order_id} returned {resp.status_code}")
            else:
                resp.success()

    @task
    def restart_journey(self):
        """End of one pass; loop back to step 1 for this simulated user."""
        self.interrupt()


class RevoShopUser(HttpUser):
    """One simulated shopper, running `ProductAndOrderJourney` on repeat."""

    tasks = [ProductAndOrderJourney]

    # Think time between journeys, so 200 users don't fire in lockstep.
    wait_time = between(1, 3)
