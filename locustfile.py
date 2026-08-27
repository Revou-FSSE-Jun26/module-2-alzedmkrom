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
"""

import random

from locust import HttpUser, LoadTestShape, SequentialTaskSet, between, task

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

            # A random in-stock product, so repeated runs don't hammer the
            # same row's stock_quantity down to zero.
            in_stock = [p for p in products if p.get("stock_quantity", 0) > 0]
            chosen = random.choice(in_stock or products)
            self.product_id = chosen["id"]

    @task
    def get_single_product(self):
        """2. GET /products/<id> — fetch the product picked above."""
        if self.product_id is None:
            return

        with self.client.get(f"/products/{self.product_id}", catch_response=True) as resp:
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
                # Insufficient stock (400) is an expected outcome under load
                # as many simulated users compete for the same product, not
                # a failure of the app itself.
                if resp.status_code == 400:
                    resp.success()
                else:
                    resp.failure(f"POST /orders returned {resp.status_code}")
                return

            self.order_id = resp.json()["id"]

    @task
    def get_created_order(self):
        """4. GET /orders/<id> — fetch the order just created."""
        if self.order_id is None:
            return

        with self.client.get(f"/orders/{self.order_id}", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /orders/{self.order_id} returned {resp.status_code}")

    @task
    def restart_journey(self):
        """End of one pass; loop back to step 1 for this simulated user."""
        self.interrupt()


class RevoShopUser(HttpUser):
    """One simulated shopper, running `ProductAndOrderJourney` on repeat."""

    tasks = [ProductAndOrderJourney]

    # Think time between journeys, so 200 users don't fire in lockstep.
    wait_time = between(1, 3)


class StepLoadShape(LoadTestShape):
    """Ramps user count in stages: 50 -> 100 -> 150 -> 200, gradually.

    Only takes effect if this file is run without an explicit --users/
    --spawn-rate on the command line; those flags are ignored once a
    LoadTestShape is defined, since the shape takes over user-count control.
    Each stage holds for `stage_duration` seconds before stepping up, at a
    spawn rate of 10 users/second.
    """

    stage_duration = 60  # seconds per stage
    stages = [50, 100, 150, 200]
    spawn_rate = 10

    def tick(self):
        run_time = self.get_run_time()
        stage_index = int(run_time // self.stage_duration)

        if stage_index >= len(self.stages):
            return None  # stop the test once the last stage's duration ends

        return (self.stages[stage_index], self.spawn_rate)
