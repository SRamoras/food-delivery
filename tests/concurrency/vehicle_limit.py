"""Scenario "vehicle limit" (rule 3): a scooter with 1 active delivery accepts 5 offers at once.

A write skew: each accept inserts a delivery for a different order, so no unique
constraint can stop it; only the lock on the courier row does. Called by the shared
runner (tests/concurrency/run.py), with the same interface as same_order.py:
  fixture() -> ctx                             reset and create the data in PostgreSQL
  await attack(ctx, mode, base_url) -> codes   fire the 5 accepts at the same time
  check(ctx) -> (holds, detail)                does rule 3 hold in PostgreSQL?
"""

import asyncio
from typing import Any

import httpx
from sqlalchemy import create_engine, text

from app.config import settings
from app.db import redis
from app.db.postgres import engine
from app.models.couriers import VEHICLE_CAPACITY

NAME = "vehicle-limit"
OFFERS = 5
LIMIT = VEHICLE_CAPACITY["scooter"]  # 2
# Fixed identities, so the next run finds and deletes what this run left behind.
NIF = "999000060"
CITY = "Concurrency city (vehicle limit)"
CUSTOMER_EMAIL = "vehicle-limit-customer@test.example"
COURIER_EMAIL = "vehicle-limit-courier@test.example"


def _reset() -> None:
    """Delete everything the previous run left, children before parents.

    Runs as the owner (MIGRATION_DATABASE_URL): fd_app has no DELETE on the
    append-only order_status_history. Only rows found by the fixed NIF and emails.
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
        couriers = ids("SELECT id FROM couriers WHERE email = :e", e=COURIER_EMAIL)
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
        run("DELETE FROM customers WHERE id = ANY(:c)", c=customers)
        zones = ids(
            "SELECT z.id FROM zones z JOIN cities c ON c.id = z.city_id WHERE c.name = :n",
            n=CITY,
        )
        run("DELETE FROM zones WHERE id = ANY(:z)", z=zones)
        run("DELETE FROM cities WHERE name = :n", n=CITY)
    owner.dispose()

    keys = [f"fd:order:{o}:track" for o in orders] + [f"fd:offer:{f}" for f in offers]
    if keys:
        redis.client.delete(*keys)


def fixture() -> dict[str, Any]:
    """Reset, then create a scooter with 1 active delivery and 5 `pending` offers to it.

    Each offer is for a different `accepted` order, so rule 1 never refuses anything
    and only rule 3 is tested. Written straight to PostgreSQL as fd_app.
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
               VALUES (:z, 'Vehicle limit', :nif, 'Rua do Teste 3', 38.7223, -9.1393,
                       0, 100, 'open')
               RETURNING id""",
            z=zone,
            nif=NIF,
        )
        customer = one(
            """INSERT INTO customers (name, email, phone, password_hash)
               VALUES ('Vehicle limit customer', :e, '+351970999999', 'x') RETURNING id""",
            e=CUSTOMER_EMAIL,
        )
        courier = one(
            """INSERT INTO couriers (name, email, phone, vehicle_type, licence_plate)
               VALUES ('Vehicle limit scooter', :e, '+351970000001', 'scooter',
                       'VL-00-AA')
               RETURNING id""",
            e=COURIER_EMAIL,
        )

        def accepted_order() -> int:
            order = one(
                """INSERT INTO orders (customer_id, restaurant_id, delivery_street,
                                       delivery_number, delivery_postcode,
                                       delivery_zone_id, delivery_lat, delivery_lng,
                                       subtotal, delivery_fee, tip, total, status)
                   VALUES (:c, :r, 'Rua A', '1', '1000-001', :z, 38.7300, -9.1500,
                           10.00, 1.50, 0, 11.50, 'accepted')
                   RETURNING id""",
                c=customer,
                r=restaurant,
                z=zone,
            )
            db.execute(
                text("""INSERT INTO order_status_history
                            (order_id, old_status, new_status, actor_type, actor_id)
                        VALUES (:o, NULL, 'placed', 'customer', :c),
                               (:o, 'placed', 'accepted', 'restaurant', :r)"""),
                {"o": order, "c": customer, "r": restaurant},
            )
            return order

        # The delivery the scooter is already on: one of its 2 slots is taken.
        busy = accepted_order()
        db.execute(
            text("INSERT INTO deliveries (order_id, courier_id) VALUES (:o, :k)"),
            {"o": busy, "k": courier},
        )
        offers = []
        for _ in range(OFFERS):
            offers.append(
                one(
                    """INSERT INTO delivery_offers (order_id, courier_id)
                       VALUES (:o, :k) RETURNING id""",
                    o=accepted_order(),
                    k=courier,
                )
            )
    return {"courier": courier, "offers": offers}


async def attack(ctx: dict[str, Any], mode: str, base_url: str) -> list[int]:
    """The scooter accepts its 5 offers, all sent together. Returns the codes."""
    params = {"mode": "naive"} if mode == "naive" else {}
    # No keep-alive: after a 500 uvicorn closes the connection (see same_order.py).
    limits = httpx.Limits(max_keepalive_connections=0)
    async with httpx.AsyncClient(
        base_url=base_url, timeout=60, limits=limits
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/couriers/{ctx['courier']}/offers/{offer}/accept", params=params
                )
                for offer in ctx["offers"]
            )
        )
    return [r.status_code for r in responses]


def check(ctx: dict[str, Any]) -> tuple[bool, str]:
    """Rule 3 holds if the scooter has at most 2 active deliveries.

    Naive mode breaks it with no error at all: every request counts 1 active delivery,
    sees room, and inserts its own delivery row.
    """
    with engine.connect() as db:
        active = db.execute(
            text("""SELECT count(*) FROM deliveries d
                      JOIN orders o ON o.id = d.order_id
                     WHERE d.courier_id = :k AND d.delivered_at IS NULL
                       AND o.status <> 'cancelled'"""),
            {"k": ctx["courier"]},
        ).scalar_one()
    return active <= LIMIT, f"active_deliveries={active} limit={LIMIT}"
