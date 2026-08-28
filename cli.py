"""Custom Flask CLI commands.

Registered against the imported `app`, so `app.py` only has to import this
module for the commands to appear under `flask --help`. Every command here runs
inside an application context, which Flask's `app.cli.command` supplies.
"""

import click
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from extensions import app, db
from models import Category, Order, Product, User, order_items

# The last row id belonging to seed.sql for each table. Anything with a
# higher id was created afterward (registration, Postman, Locust, etc.) and
# is safe for `flask reset-test-data` to remove. See seed.sql: 10 users,
# 10 products, 30 orders.
SEEDED_MAX_USER_ID = 10
SEEDED_MAX_PRODUCT_ID = 10
SEEDED_MAX_ORDER_ID = 30

# products.stock_quantity exactly as inserted by seed.sql, keyed by product
# id. `flask reset-test-data` restores every product to these values,
# undoing whatever `create_order`/`update_order_status` deducted or
# restored during testing.
SEEDED_PRODUCT_STOCK = {
    1: 50,
    2: 200,
    3: 80,
    4: 150,
    5: 30,
    6: 300,
    7: 60,
    8: 100,
    9: 45,
    10: 75,
}

# Order 4 (Windbreaker Jacket, qty 1) is extended rather than replaced, so the
# `queries.sql` check expecting exactly three orders per user keeps passing.
# Products 1 and 2 aren't yet linked to order 4 (seed.sql order_items has only
# the (4, 5, 1) row), so they're the two added to make it a three-product order.
LINK_ORDER_ID = 4
NEW_ORDER_ITEMS = (
    # (product_id, quantity)
    (1, 1),
    (2, 2),
)

# The five Checkpoint 1 tables, in dependency order, paired with the label used
# in the printed report. Values are Table objects so a plain COUNT(*) works for
# both the mapped models and the association table.
TABLES = (
    ("users", User.__table__),
    ("categories", Category.__table__),
    ("products", Product.__table__),
    ("orders", Order.__table__),
    ("order_items", order_items),
)


def _scrub(message, secret):
    """Return `message` with `secret` masked, so no password reaches stdout."""
    text_message = str(message)
    if secret:
        text_message = text_message.replace(secret, "***")
    return text_message


@app.cli.command("check-db")
def check_db():
    """Verify the live database connection and report per-table row counts."""
    # `render_as_string(hide_password=True)` is what keeps the credential out of
    # the output: the URL is only ever printed through that masked form.
    url = db.engine.url
    password = url.password
    click.echo(f"Target URI:  {url.render_as_string(hide_password=True)}")
    click.echo(f"Database:    {url.database}")
    click.echo(f"Host:        {url.host}:{url.port or 5432}")
    click.echo(f"User:        {url.username}")

    try:
        with db.engine.connect() as connection:
            version = connection.execute(text("SELECT version()")).scalar()
            click.echo(f"Server:      {version}")

            # Confirms the connection resolved to the database we asked for.
            current = connection.execute(text("SELECT current_database()")).scalar()
            click.echo(f"Connected:   {current}")

            click.echo("")
            click.echo("Row counts:")
            for label, table in TABLES:
                count = connection.execute(
                    select(func.count()).select_from(table)
                ).scalar()
                click.echo(f"  {label:<12} {count}")
    except SQLAlchemyError as exc:
        click.secho("", err=True)
        click.secho("Database check failed.", fg="red", err=True)
        click.secho(f"  {type(exc).__name__}: {_scrub(exc, password)}", err=True)
        click.secho(
            "  Confirm the PostgreSQL server is running and that "
            f"'{url.database}' exists and is reachable.",
            err=True,
        )
        raise SystemExit(1)

    click.echo("")
    click.secho("Connection OK.", fg="green")


@app.cli.command("reset-test-data")
def reset_test_data():
    """Undo the write side-effects of local load/manual testing.

    `create_order` (POST /orders) commits real rows against whatever
    database `DATABASE_URL` points at and deducts real `stock_quantity`;
    running the Locust journey, exercising Postman, or manual testing
    against a local `revoshop_db` all leave those rows and deductions
    behind, since nothing about a normal HTTP request is aware it came
    from a load test. This command reverses that:

      1. Deletes every `order_items` row whose `order_id` is above the
         seeded range (`SEEDED_MAX_ORDER_ID`).
      2. Deletes every `orders` row above that same id.
      3. Deletes every `users` row above `SEEDED_MAX_USER_ID` (e.g. from
         repeatedly hitting `POST /users` during testing).
      4. Deletes every `products` row above `SEEDED_MAX_PRODUCT_ID` (e.g.
         a product created via Postman/pytest exploration that was never
         cleaned up).
      5. Resets every seeded product's `stock_quantity` back to its exact
         `seed.sql` value (`SEEDED_PRODUCT_STOCK`) and clears `is_delete`
         on all of them, undoing any soft-delete from `DELETE
         /products/<id>`.

    Does not touch `categories`, since nothing in this project deletes or
    creates categories as a side effect of order/product testing.

    Safe to run repeatedly: if there is nothing above the seeded range,
    steps 1-4 delete zero rows, and step 5 just re-applies the same values.
    """
    try:
        deleted_items = db.session.execute(
            text("DELETE FROM order_items WHERE order_id > :max_id"),
            {"max_id": SEEDED_MAX_ORDER_ID},
        ).rowcount
        deleted_orders = db.session.execute(
            text("DELETE FROM orders WHERE id > :max_id"),
            {"max_id": SEEDED_MAX_ORDER_ID},
        ).rowcount
        deleted_users = db.session.execute(
            text("DELETE FROM users WHERE id > :max_id"),
            {"max_id": SEEDED_MAX_USER_ID},
        ).rowcount
        deleted_products = db.session.execute(
            text("DELETE FROM products WHERE id > :max_id"),
            {"max_id": SEEDED_MAX_PRODUCT_ID},
        ).rowcount

        for product_id, stock_quantity in SEEDED_PRODUCT_STOCK.items():
            db.session.execute(
                text(
                    "UPDATE products SET stock_quantity = :qty, is_delete = false "
                    "WHERE id = :pid"
                ),
                {"qty": stock_quantity, "pid": product_id},
            )

        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        click.secho("Resetting test data failed.", fg="red", err=True)
        click.secho(f"  {type(exc).__name__}: {exc}", err=True)
        raise SystemExit(1)

    click.echo(f"Deleted {deleted_orders} test order(s) and {deleted_items} order_items row(s).")
    click.echo(f"Deleted {deleted_users} test user(s) and {deleted_products} test product(s).")
    click.echo(f"Reset stock_quantity and is_delete on all {len(SEEDED_PRODUCT_STOCK)} seeded products.")


@app.cli.command("link-order-products")
def link_order_products():
    """Link order 4 to two more products, demonstrating the many-to-many.

    Order 4 already holds one product (Windbreaker Jacket). This extends it
    with two more products instead of creating a new order, so the
    `queries.sql` check expecting exactly three orders per user stays green.
    """
    try:
        # 11.1: insert one order_items row per new product, with unit_price
        # read live from Product.price and a safe on-conflict clause so
        # repeat runs never duplicate rows or error on the composite PK.
        for product_id, quantity in NEW_ORDER_ITEMS:
            product = db.session.get(Product, product_id)
            if product is None:
                click.secho(
                    f"Product {product_id} was not found; skipping.",
                    fg="yellow",
                )
                continue

            stmt = (
                insert(order_items)
                .values(
                    order_id=LINK_ORDER_ID,
                    product_id=product_id,
                    quantity=quantity,
                    unit_price=product.price,
                )
                .on_conflict_do_nothing(
                    index_elements=["order_id", "product_id"],
                )
            )
            db.session.execute(stmt)

        db.session.commit()

        order = db.session.get(Order, LINK_ORDER_ID)
        if order is None:
            click.secho(
                f"Order {LINK_ORDER_ID} was not found; nothing to link.",
                fg="red",
                err=True,
            )
            raise SystemExit(1)

        # 11.2: recompute order 4's total_price as the sum of quantity *
        # unit_price over all of its association rows, then commit. A order
        # with no association rows would make the SUM NULL, which violates
        # the NOT NULL constraint on total_price, so that case falls back to 0.
        new_total = db.session.execute(
            select(
                func.sum(order_items.c.quantity * order_items.c.unit_price)
            ).where(order_items.c.order_id == LINK_ORDER_ID)
        ).scalar()

        order.total_price = new_total if new_total is not None else 0
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        click.secho("Linking order products failed.", fg="red", err=True)
        click.secho(f"  {type(exc).__name__}: {exc}", err=True)
        raise SystemExit(1)

    # Reload order 4 through the ORM so `products` reflects the new rows.
    db.session.expire(order)
    order = db.session.get(Order, LINK_ORDER_ID)
    click.echo(f"Order {order.id} total_price: {order.total_price}")
    click.echo(f"Order {order.id} products: {order.products}")
