"""Locust load test for RevoShop.

Simulates a sequential shopper journey against a running server:
  1. POST /users + POST /auth/login   once per simulated user, in on_start
  2. GET  /products                   list all products (public)
  3. GET  /products/<id>              fetch a single product from that list
  4. POST /orders                     place an order  (requires access token)
  5. GET  /orders/<id>                fetch the order just created (token)
  6. POST /auth/refresh               occasionally, to rotate tokens

Run locally (server must already be running, e.g. `flask run`):

    locust -f locustfile.py --host=http://127.0.0.1:5000

Then open http://localhost:8089 and start a swarm (e.g. 50 users, ramping
to 200, spawn rate a few per second), or run headless:

    locust -f locustfile.py --host=http://127.0.0.1:5000 \
        --users 200 --spawn-rate 10 --run-time 2m --headless

Authentication
--------------
The order endpoints require `Authorization: Bearer <access token>` and take
the order's owner from that token, so there is no `user_id` in the request
body any more.

Each simulated user registers its own throwaway account in `on_start` and
logs in with it. It does not reuse a seeded account, for a concrete reason:
`seed.sql` stores placeholder strings such as `hash_budi_001` in
`password_hash` rather than real Werkzeug hashes, so no seeded user can
authenticate at all. Registering also keeps the test self-contained — it
works against a freshly migrated database with no manual setup.

Set `LOCUST_EMAIL` and `LOCUST_PASSWORD` to log in as one existing account
instead (every simulated user then shares it, which is closer to a hot-key
scenario than to real traffic).

`POST /auth/refresh` runs on roughly one journey in five. It is included
because refreshing is not free: rotation writes a row to `token_blocklist`
and every authenticated request reads that table, so the refresh path
deserves to appear in the numbers rather than being assumed cheap.

IMPORTANT — cleanup after running this:

`create_order` commits real rows and deducts real `stock_quantity`. Nothing
here reverts those writes — they are permanent commits, same as if typed by
hand. Registration and refresh also leave rows behind (`users`, and
`token_blocklist`). A long run can deplete every product's stock to 0, after
which `POST /orders` starts failing on insufficient stock.

Point the server at a throwaway database before running this, not at data you
care about. See `.env.example` for how to set `DATABASE_URL` for a load-test
database before starting `flask run`.
"""

import os
import random
import uuid

from locust import HttpUser, SequentialTaskSet, between, task

# Optional: log in as an existing account instead of registering one.
# Both must be set for this to take effect.
EXISTING_EMAIL = os.environ.get("LOCUST_EMAIL", "").strip()
EXISTING_PASSWORD = os.environ.get("LOCUST_PASSWORD", "").strip()

# Password used for the throwaway accounts this file registers.
GENERATED_PASSWORD = "LocustLoadTest!2026"


class ProductAndOrderJourney(SequentialTaskSet):
    """One pass through the journey, in order, per simulated user."""

    def on_start(self):
        self.product_id = None
        self.order_id = None

    # -- helpers ------------------------------------------------------------

    @property
    def auth_headers(self):
        """Bearer header for the parent user's current access token."""
        return {"Authorization": f"Bearer {self.user.access_token}"}

    # -- journey ------------------------------------------------------------

    @task
    def list_products(self):
        """1. GET /products — list all products, remember one id. Public."""
        with self.client.get("/products", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /products returned {resp.status_code}")
                return

            products = resp.json()
            if not products:
                resp.failure("GET /products returned an empty list")
                return

            # A random product, so repeated runs don't hammer the same row's
            # stock_quantity down to zero.
            self.product_id = random.choice(products)["id"]

    @task
    def get_single_product(self):
        """2. GET /products/<id> — fetch the product picked above. Public."""
        if self.product_id is None:
            return

        with self.client.get(
            f"/products/{self.product_id}", name="/products/[id]", catch_response=True
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /products/{self.product_id} returned {resp.status_code}")

    @task
    def create_order(self):
        """3. POST /orders — place a 1-unit order. Requires an access token.

        Any non-201 counts as a real failure, including a 400 from
        insufficient/zero stock, so stock depletion shows up in the failure
        stats instead of being hidden as success.
        """
        if self.product_id is None or not self.user.access_token:
            return

        body = {"items": [{"product_id": self.product_id, "quantity": 1}]}
        with self.client.post(
            "/orders", json=body, headers=self.auth_headers, catch_response=True
        ) as resp:
            if resp.status_code == 201:
                self.order_id = resp.json()["id"]
                return

            # An expired access token is the one recoverable failure: refresh
            # and let the next journey proceed, rather than counting the
            # server as broken.
            if resp.status_code == 401 and resp.json().get("code") == "token_expired":
                resp.success()
                self.user.refresh_access_token()
                return

            resp.failure(f"POST /orders returned {resp.status_code}")

    @task
    def get_created_order(self):
        """4. GET /orders/<id> — fetch the order just created. Requires a token."""
        if self.order_id is None or not self.user.access_token:
            return

        with self.client.get(
            f"/orders/{self.order_id}",
            name="/orders/[id]",
            headers=self.auth_headers,
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"GET /orders/{self.order_id} returned {resp.status_code}")

    @task
    def maybe_refresh_token(self):
        """5. POST /auth/refresh — rotate tokens on ~1 journey in 5."""
        if not self.user.refresh_token or random.random() > 0.2:
            return
        self.user.refresh_access_token()

    @task
    def restart_journey(self):
        """End of one pass; loop back to step 1 for this simulated user."""
        self.interrupt()


class RevoShopUser(HttpUser):
    """One simulated shopper, running `ProductAndOrderJourney` on repeat."""

    tasks = [ProductAndOrderJourney]

    # Think time between journeys, so 200 users don't fire in lockstep.
    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate once, before this user's first journey."""
        self.access_token = None
        self.refresh_token = None

        if EXISTING_EMAIL and EXISTING_PASSWORD:
            self.login(EXISTING_EMAIL, EXISTING_PASSWORD)
            return

        email, password = self.register()
        if email:
            self.login(email, password)

    def register(self):
        """Create a throwaway account. Returns (email, password) or (None, None)."""
        suffix = uuid.uuid4().hex[:12]
        email = f"locust_{suffix}@example.com"
        body = {
            "username": f"locust_{suffix}",
            "email": email,
            "password": GENERATED_PASSWORD,
        }
        with self.client.post(
            "/users", json=body, name="/users (register)", catch_response=True
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"POST /users returned {resp.status_code}")
                return None, None
        return email, GENERATED_PASSWORD

    def login(self, email, password):
        """Exchange credentials for a token pair and store both."""
        with self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
            name="/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"POST /auth/login returned {resp.status_code}")
                return
            body = resp.json()
            self.access_token = body["access_token"]
            self.refresh_token = body["refresh_token"]

    def refresh_access_token(self):
        """Rotate the token pair.

        The refresh token presented is revoked server-side as part of this
        call, so both halves of the new pair must be stored — keeping the old
        refresh token would guarantee a `token_revoked` failure next time.
        """
        if not self.refresh_token:
            return

        with self.client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {self.refresh_token}"},
            name="/auth/refresh",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"POST /auth/refresh returned {resp.status_code}")
                # The session is over; stop sending authenticated requests
                # rather than generating a stream of guaranteed 401s.
                self.access_token = None
                self.refresh_token = None
                return
            body = resp.json()
            self.access_token = body["access_token"]
            self.refresh_token = body["refresh_token"]
