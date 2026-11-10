"""Scenario "last portions" (rule 2): 60 customers race for the last 30 portions of an item.

Called by the shared runner (tests/concurrency/run.py, jcleberfernandes's), which
counts the status codes and prints the result:
  fixture() -> ctx                          reset and create the data in PostgreSQL
  await attack(ctx, mode, base_url) -> codes   fire the 60 orders at the same time
  check(ctx) -> (holds, detail)             does rule 2 hold in PostgreSQL?
"""

import asyncio
from typing import Any

import httpx
from sqlalchemy import create_engine, text

from app.config import settings
from app.db import redis
from app.db.postgres import engine

NAME = "last-portions"
STOCK = 30
CUSTOMERS = 60
# Fixed identities, so the next run finds and deletes what this run left behind.
NIF = "999000030"
CITY = "Concurrency city (last portions)"
EMAIL = "last-portions-{i}@test.example"
PHONE = "+351990000{i:03d}"


def _reset() -> None:
    """Delete everything the previous run left: orders first, then the catalogue.

    Runs as the owner (MIGRATION_DATABASE_URL), not fd_app: fd_app has no DELETE on
    order_status_history (append-only by design), and that grant is not loosened for
    a test. Only this scenario's rows are touched, found by their fixed NIF and emails.
    """
    if not settings.migration_database_url:
        raise RuntimeError("MIGRATION_DATABASE_URL is needed to reset the scenario")
    owner = create_engine(settings.migration_database_url)
    with owner.begin() as db:

        def ids(sql: str, **params: Any) -> list[int]:
            return list(db.execute(text(sql), params).scalars())

        def run(sql: str, **params: Any) -> None:
            db.execute(text(sql), params)

        restaurants = ids("SELECT id FROM restaurants WHERE nif = :n", n=NIF)
        customers = ids(
            "SELECT id FROM customers WHERE email LIKE :e",
            e=EMAIL.format(i="%"),
        )
        orders = ids(
            "SELECT id FROM orders WHERE restaurant_id = ANY(:r) OR customer_id = ANY(:c)",
            r=restaurants,
            c=customers,
        )
        items = ids(
            """SELECT i.id FROM menu_items i
                 JOIN menu_categories c ON c.id = i.category_id
                WHERE c.restaurant_id = ANY(:r)""",
            r=restaurants,
        )
        # Children before parents: several of these foreign keys are RESTRICT.
        run("DELETE FROM order_status_history WHERE order_id = ANY(:o)", o=orders)
        run("DELETE FROM payments WHERE order_id = ANY(:o)", o=orders)
        run("DELETE FROM deliveries WHERE order_id = ANY(:o)", o=orders)
        run("DELETE FROM delivery_offers WHERE order_id = ANY(:o)", o=orders)
        run("DELETE FROM order_lines WHERE order_id = ANY(:o)", o=orders)
        run("DELETE FROM orders WHERE id = ANY(:o)", o=orders)
        run("DELETE FROM daily_stock WHERE item_id = ANY(:i)", i=items)
        run("DELETE FROM menu_items WHERE id = ANY(:i)", i=items)
        run("DELETE FROM menu_categories WHERE restaurant_id = ANY(:r)", r=restaurants)
        run("DELETE FROM opening_periods WHERE restaurant_id = ANY(:r)", r=restaurants)
        run("DELETE FROM restaurants WHERE id = ANY(:r)", r=restaurants)
        run("DELETE FROM customer_addresses WHERE customer_id = ANY(:c)", c=customers)
        run("DELETE FROM customers WHERE id = ANY(:c)", c=customers)
        zones = ids(
            "SELECT z.id FROM zones z JOIN cities c ON c.id = z.city_id WHERE c.name = :n",
            n=CITY,
        )
        run(
            """DELETE FROM zone_fees
                WHERE restaurant_zone_id = ANY(:z) OR customer_zone_id = ANY(:z)""",
            z=zones,
        )
        run("DELETE FROM zones WHERE id = ANY(:z)", z=zones)
        run("DELETE FROM cities WHERE name = :n", n=CITY)
    owner.dispose()

    # The derived Redis keys of the deleted rows, so redis/verify.py stays clean.
    keys = [f"fd:order:{o}:track" for o in orders]
    for item in items:
        keys += list(redis.client.scan_iter(f"fd:stock:{item}:*"))
    if keys:
        redis.client.delete(*keys)


def fixture() -> dict[str, Any]:
    """Reset, then create 1 restaurant open 00:00-24:00 every day, 1 item with stock 30
    and 60 customers with an address in a delivered zone (written as fd_app)."""
    _reset()
    with engine.begin() as db:

        def one(sql: str, **params: Any) -> int:
            return db.execute(text(sql), params).scalar_one()

        city = one("INSERT INTO cities (name) VALUES (:n) RETURNING id", n=CITY)
        zone = one(
            "INSERT INTO zones (city_id, name) VALUES (:c, 'Centro') RETURNING id",
            c=city,
        )
        restaurant = one(
            """INSERT INTO restaurants (zone_id, name, nif, address, lat, lng,
                                        min_order_value, kitchen_capacity, status)
               VALUES (:z, 'Last portions', :nif, 'Rua do Teste 1', 38.7223, -9.1393,
                       0, 100, 'open')
               RETURNING id""",
            z=zone,
            nif=NIF,
        )
        # 00:00-24:00 on all 7 days, so the test runs at any hour.
        db.execute(
            text("""INSERT INTO opening_periods (restaurant_id, weekday, hours)
                    SELECT :r, d, int4range(0, 1440) FROM generate_series(0, 6) d"""),
            {"r": restaurant},
        )
        # Restaurant and customers in the same zone: a delivered zone.
        db.execute(
            text("""INSERT INTO zone_fees (restaurant_zone_id, customer_zone_id, fee)
                    VALUES (:z, :z, 1.50)"""),
            {"z": zone},
        )
        category = one(
            """INSERT INTO menu_categories (restaurant_id, name)
               VALUES (:r, 'Pratos') RETURNING id""",
            r=restaurant,
        )
        # daily_stock on the item: today's daily_stock row is created from it on the
        # first order (lazy reset), so the race also covers that first INSERT.
        item = one(
            """INSERT INTO menu_items (category_id, name, price, daily_stock)
               VALUES (:c, 'Prato do dia', 8.00, :s) RETURNING id""",
            c=category,
            s=STOCK,
        )
        customers = []
        for i in range(CUSTOMERS):
            customer = one(
                """INSERT INTO customers (name, email, phone, password_hash)
                   VALUES (:n, :e, :p, 'x') RETURNING id""",
                n=f"Customer {i}",
                e=EMAIL.format(i=i),
                p=PHONE.format(i=i),
            )
            address = one(
                """INSERT INTO customer_addresses
                       (customer_id, zone_id, street, number, postcode, lat, lng)
                   VALUES (:c, :z, 'Rua A', '1', '1000-001', 38.7300, -9.1500)
                   RETURNING id""",
                c=customer,
                z=zone,
            )
            customers.append((customer, address))
    return {"restaurant": restaurant, "item": item, "customers": customers}


async def attack(ctx: dict[str, Any], mode: str, base_url: str) -> list[int]:
    """60 orders of 1 portion each (card, approved), all sent together. Returns the codes.

    asyncio.gather starts every request before any answer arrives, so they reach the
    API at the same time; FastAPI runs them in its thread pool, in parallel in PG.
    """
    params = {"mode": "naive"} if mode == "naive" else {}
    # 60 connections at once: the default pool (100) and a long timeout, because the
    # real mode queues on the stock row lock.
    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/customers/{customer}/orders",
                    params=params,
                    json={
                        "address_id": address,
                        "lines": [{"item_id": ctx["item"], "quantity": 1}],
                        "payment_method": "card",
                        "simulate": "approved",
                    },
                )
                for customer, address in ctx["customers"]
            )
        )
    return [r.status_code for r in responses]


def check(ctx: dict[str, Any]) -> tuple[bool, str]:
    """Rule 2 holds if the stock ended at 0 and exactly 30 orders exist.

    Naive mode breaks it with a lost update: requests read the same `remaining` and
    write the same new value, so more than 30 orders exist and stock is left over.
    """
    with engine.connect() as db:
        orders = db.execute(
            text("SELECT count(*) FROM orders WHERE restaurant_id = :r"),
            {"r": ctx["restaurant"]},
        ).scalar_one()
        remaining = db.execute(
            text("SELECT remaining FROM daily_stock WHERE item_id = :i"),
            {"i": ctx["item"]},
        ).scalar_one_or_none()
    holds = remaining == 0 and orders == STOCK
    return holds, f"orders={orders} stock_left={remaining}"
