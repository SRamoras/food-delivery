"""Scenario "same order" (rule 1): 50 couriers accept the same order at the same time.

Called by the shared runner (tests/concurrency/run.py, jcleberfernandes's), which
counts the status codes and prints the result. Same interface as last_portions.py:
  fixture() -> ctx                             reset and create the data in PostgreSQL
  await attack(ctx, mode, base_url) -> codes   fire the 50 accepts at the same time
  check(ctx) -> (holds, detail)                does rule 1 hold in PostgreSQL?
"""

import asyncio
from typing import Any

import httpx
from sqlalchemy import create_engine, text

from app.config import settings
from app.db import redis
from app.db.postgres import engine

NAME = "same-order"
COURIERS = 50
# Fixed identities, so the next run finds and deletes what this run left behind.
NIF = "999000050"
CITY = "Concurrency city (same order)"
CUSTOMER_EMAIL = "same-order-customer@test.example"
COURIER_EMAIL = "same-order-courier-{i}@test.example"
COURIER_PHONE = "+351980000{i:03d}"
COURIER_PLATE = "SO-{i:02d}-AA"


def _reset() -> None:
    """Delete everything the previous run left, children before parents.

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
        customers = ids("SELECT id FROM customers WHERE email = :e", e=CUSTOMER_EMAIL)
        couriers = ids(
            "SELECT id FROM couriers WHERE email LIKE :e",
            e=COURIER_EMAIL.format(i="%"),
        )
        orders = ids(
            "SELECT id FROM orders WHERE restaurant_id = ANY(:r) OR customer_id = ANY(:c)",
            r=restaurants,
            c=customers,
        )
        offers = ids(
            "SELECT id FROM delivery_offers WHERE order_id = ANY(:o) OR courier_id = ANY(:k)",
            o=orders,
            k=couriers,
        )
        # Several of these foreign keys are RESTRICT, so the order matters.
        run(
            "DELETE FROM deliveries WHERE order_id = ANY(:o) OR courier_id = ANY(:k)",
            o=orders,
            k=couriers,
        )
        run("DELETE FROM delivery_offers WHERE id = ANY(:f)", f=offers)
        run("DELETE FROM order_status_history WHERE order_id = ANY(:o)", o=orders)
        run("DELETE FROM orders WHERE id = ANY(:o)", o=orders)
        run("DELETE FROM couriers WHERE id = ANY(:k)", k=couriers)
        run("DELETE FROM restaurants WHERE id = ANY(:r)", r=restaurants)
        run("DELETE FROM customer_addresses WHERE customer_id = ANY(:c)", c=customers)
        run("DELETE FROM customers WHERE id = ANY(:c)", c=customers)
        zones = ids(
            "SELECT z.id FROM zones z JOIN cities c ON c.id = z.city_id WHERE c.name = :n",
            n=CITY,
        )
        run("DELETE FROM zones WHERE id = ANY(:z)", z=zones)
        run("DELETE FROM cities WHERE name = :n", n=CITY)
    owner.dispose()

    # The Redis keys of the deleted rows, so redis/verify.py stays clean.
    keys = [f"fd:order:{o}:track" for o in orders] + [f"fd:offer:{f}" for f in offers]
    if keys:
        redis.client.delete(*keys)


def fixture() -> dict[str, Any]:
    """Reset, then create 1 `accepted` order, 50 active couriers and 50 `pending` offers.

    Written straight to PostgreSQL as fd_app: F4 only needs the order, the couriers and
    the offers, so this scenario does not depend on F2, F3 or F7. The couriers are
    cars with no active delivery (room for 3), so only rule 1 can refuse them. The
    offers are sent now, so they are well inside their 45 s when the attack starts.
    """
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
               VALUES (:z, 'Same order', :nif, 'Rua do Teste 2', 38.7223, -9.1393,
                       0, 100, 'open')
               RETURNING id""",
            z=zone,
            nif=NIF,
        )
        customer = one(
            """INSERT INTO customers (name, email, phone, password_hash)
               VALUES ('Same order customer', :e, '+351980999999', 'x') RETURNING id""",
            e=CUSTOMER_EMAIL,
        )
        order = one(
            """INSERT INTO orders (customer_id, restaurant_id, delivery_street,
                                   delivery_number, delivery_postcode, delivery_zone_id,
                                   delivery_lat, delivery_lng, subtotal, delivery_fee,
                                   tip, total, status)
               VALUES (:c, :r, 'Rua A', '1', '1000-001', :z, 38.7300, -9.1500,
                       10.00, 1.50, 0, 11.50, 'accepted')
               RETURNING id""",
            c=customer,
            r=restaurant,
            z=zone,
        )
        # The history the order would have if it had gone through F2 and F3.
        db.execute(
            text("""INSERT INTO order_status_history
                        (order_id, old_status, new_status, actor_type, actor_id)
                    VALUES (:o, NULL, 'placed', 'customer', :c),
                           (:o, 'placed', 'accepted', 'restaurant', :r)"""),
            {"o": order, "c": customer, "r": restaurant},
        )
        offers = []
        for i in range(COURIERS):
            courier = one(
                """INSERT INTO couriers (name, email, phone, vehicle_type, licence_plate)
                   VALUES (:n, :e, :p, 'car', :plate) RETURNING id""",
                n=f"Courier {i}",
                e=COURIER_EMAIL.format(i=i),
                p=COURIER_PHONE.format(i=i),
                plate=COURIER_PLATE.format(i=i),
            )
            offer = one(
                """INSERT INTO delivery_offers (order_id, courier_id)
                   VALUES (:o, :k) RETURNING id""",
                o=order,
                k=courier,
            )
            offers.append((courier, offer))
    return {"order": order, "offers": offers}


async def attack(ctx: dict[str, Any], mode: str, base_url: str) -> list[int]:
    """50 accepts, one per courier and offer, all sent together. Returns the codes.

    asyncio.gather starts every request before any answer arrives, so they reach the
    API at the same time; FastAPI runs them in its thread pool, in parallel in PG.
    """
    params = {"mode": "naive"} if mode == "naive" else {}
    # No keep-alive: after a 500 (naive mode) uvicorn closes the connection, and a
    # reused one would fail in the client with ReadError instead of counting the 500.
    limits = httpx.Limits(max_keepalive_connections=0)
    async with httpx.AsyncClient(
        base_url=base_url, timeout=60, limits=limits
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post(f"/couriers/{courier}/offers/{offer}/accept", params=params)
                for courier, offer in ctx["offers"]
            )
        )
    return [r.status_code for r in responses]


def check(ctx: dict[str, Any]) -> tuple[bool, str]:
    """Rule 1 holds if the order has exactly one delivery and one accepted offer.

    In naive mode UNIQUE (order_id) on deliveries still keeps one delivery, so the
    race shows up as 5xx (the unique violations) rather than as broken data.
    """
    with engine.connect() as db:
        deliveries = db.execute(
            text("SELECT count(*) FROM deliveries WHERE order_id = :o"),
            {"o": ctx["order"]},
        ).scalar_one()
        accepted = db.execute(
            text("""SELECT count(*) FROM delivery_offers
                     WHERE order_id = :o AND outcome = 'accepted'"""),
            {"o": ctx["order"]},
        ).scalar_one()
    holds = deliveries == 1 and accepted == 1
    return holds, f"deliveries={deliveries} accepted_offers={accepted}"
