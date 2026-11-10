"""Couriers seed: 2,500 couriers, delivery offers and deliveries for the seeded orders (COPY).

Runs after B's orders seed (it needs the orders and their status history) and before
the Mongo position seed (see scripts/seed.sh). Deterministic (random.seed(42)) and
uneven: in each city a few couriers do most of the deliveries. Every row respects the
constraints; nothing is disabled.
"""

import random
import time
from bisect import bisect
from collections import defaultdict
from datetime import UTC, timedelta
from itertools import accumulate
from string import ascii_uppercase

import psycopg

from app.config import settings
from app.models.couriers import VEHICLE_CAPACITY
from app.models.offers import OFFER_TTL_SECONDS
from app.services.orders import distance_km

random.seed(42)

COURIERS = 2_500
VEHICLES = (["bicycle", "scooter", "car"], [35, 45, 20])
BLOCKED = 0.02  # blocked couriers get no offers or deliveries in the seed
FIRST_NAMES = [
    "Ana",
    "Bruno",
    "Carla",
    "Diogo",
    "Eva",
    "Filipe",
    "Gonçalo",
    "Helena",
    "Inês",
    "João",
    "Joana",
    "Luís",
    "Marta",
    "Miguel",
    "Nuno",
    "Pedro",
    "Rita",
    "Rui",
    "Sara",
    "Sofia",
    "Tiago",
    "Vasco",
]
LAST_NAMES = [
    "Almeida",
    "Barbosa",
    "Carvalho",
    "Costa",
    "Ferreira",
    "Gomes",
    "Lopes",
    "Marques",
    "Martins",
    "Mendes",
    "Oliveira",
    "Pereira",
    "Pinto",
    "Ribeiro",
    "Rodrigues",
    "Santos",
    "Silva",
    "Sousa",
    "Teixeira",
    "Vieira",
]

# ~1.5 offers per order with a courier: the winner, sometimes an earlier wave that
# nobody took (expired), and sometimes other couriers of the winning wave.
EXPIRED_WAVE = 0.2
EXTRA_IN_WAVE = ([0, 1, 2], [75, 20, 5])
EXTRA_OUTCOME = (["withdrawn", "rejected"], [70, 30])
# Share of orders still in the kitchen whose courier has already accepted.
IN_KITCHEN_WITH_COURIER = 0.6


def plate(n: int) -> str:
    """Unique Portuguese-style plate (AA-00-AA) derived from the courier number."""
    letters = []
    rest, digits = divmod(n, 100)
    for _ in range(4):
        rest, i = divmod(rest, 26)
        letters.append(ascii_uppercase[i])
    return f"{letters[0]}{letters[1]}-{digits:02d}-{letters[2]}{letters[3]}"


def zipf_cum(n: int, s: float) -> list[float]:
    """Cumulative Zipf weights for n things in a random order: rank k weighs 1/k^s."""
    ranks = list(range(1, n + 1))
    random.shuffle(ranks)
    return list(accumulate(1 / r**s for r in ranks))


def load_couriers(cur: psycopg.Cursor, cities: list[int]) -> dict[int, list]:
    """Insert the couriers and return, per city, the active ones with their weights.

    Couriers have no city column; the city only decides which orders a courier takes
    here, so offers and deliveries stay local (a Porto courier never delivers in Faro).
    """
    rows, home = [], []
    for n in range(COURIERS):
        vehicle = random.choices(*VEHICLES)[0]
        status = "blocked" if random.random() < BLOCKED else "active"
        rows.append(
            (
                f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                f"courier{n}@couriers.example",
                f"+35196{n:07d}",
                vehicle,
                None if vehicle == "bicycle" else plate(n),
                status,
            )
        )
        home.append(random.choice(cities))
    with cur.copy(
        "COPY couriers (name, email, phone, vehicle_type, licence_plate, status)"
        " FROM STDIN"
    ) as cp:
        for row in rows:
            cp.write_row(row)
    # The emails are unique and numbered, so they give back each row's id.
    cur.execute(
        "SELECT id, email FROM couriers WHERE email LIKE 'courier%@couriers.example'"
    )
    ids = {email: cid for cid, email in cur.fetchall()}

    by_city: dict[int, list] = defaultdict(list)
    for n, row in enumerate(rows):
        if row[5] == "active":
            by_city[home[n]].append((ids[row[1]], row[3]))
    return {
        city: (lst, zipf_cum(len(lst), 0.9)) for city, lst in by_city.items() if lst
    }


def load_orders(cur: psycopg.Cursor) -> list[tuple]:
    """Orders the restaurant accepted, with the times the history says each step ran."""
    cur.execute(
        """
        SELECT o.id, o.status, z.city_id, r.lat, r.lng, o.delivery_lat, o.delivery_lng,
               max(h.changed_at) FILTER (WHERE h.new_status = 'accepted'),
               max(h.changed_at) FILTER (WHERE h.new_status = 'picked_up'),
               max(h.changed_at) FILTER (WHERE h.new_status = 'delivered')
          FROM orders o
          JOIN restaurants r ON r.id = o.restaurant_id
          JOIN zones z ON z.id = r.zone_id
          JOIN order_status_history h ON h.order_id = o.id
         WHERE o.status NOT IN ('placed', 'rejected')
         GROUP BY o.id, z.city_id, r.lat, r.lng
         ORDER BY o.id
        """
    )
    return cur.fetchall()


def main() -> None:
    """Generate and load everything in one transaction: a failure leaves no couriers."""
    started = time.monotonic()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM couriers)")
        if cur.fetchone()[0]:
            print("couriers already seeded, skipped")
            return
        cur.execute("SELECT id FROM cities ORDER BY id")
        cities = [row[0] for row in cur.fetchall()]
        if not cities:
            raise SystemExit("no cities: run C's catalogue seed first")
        pools = load_couriers(cur, cities)
        orders = load_orders(cur)
        print(f"  {COURIERS} couriers, {len(orders)} accepted orders read")

        # Statement time, the same clock the app uses for offer validity.
        cur.execute("SELECT now()")
        now = cur.fetchone()[0].astimezone(UTC)
        ttl = timedelta(seconds=OFFER_TTL_SECONDS)
        # Active deliveries per courier right now: rule 3 must hold for the seed too.
        active: dict[int, int] = defaultdict(int)
        offers, deliveries = [], []

        for (
            oid,
            status,
            city,
            rlat,
            rlng,
            dlat,
            dlng,
            accepted,
            picked_up,
            delivered,
        ) in orders:
            pool = pools.get(city)
            if pool is None or accepted is None:
                continue
            couriers, cum = pool
            # Distinct couriers for this order: UNIQUE (order_id, courier_id).
            n_extra = random.choices(*EXTRA_IN_WAVE)[0]
            expired_wave = random.random() < EXPIRED_WAVE
            wanted = 1 + n_extra + expired_wave
            chosen: dict[int, str] = {}
            for _ in range(wanted * 4):
                cid, vehicle = couriers[bisect(cum, random.random() * cum[-1])]
                chosen.setdefault(cid, vehicle)
                if len(chosen) == wanted:
                    break
            picks = list(chosen.items())

            # Waves: an expired first wave, then the wave the winner accepted.
            sent = accepted + timedelta(seconds=random.uniform(2, 20))
            if expired_wave and len(picks) > 1:
                cid, _ = picks.pop()
                offers.append((oid, cid, sent, "expired"))
                sent += ttl + timedelta(seconds=random.uniform(1, 10))
            if sent > now:
                continue  # accepted seconds ago: not offered yet
            took = sent + timedelta(seconds=random.uniform(3, 40))

            has_courier = status in ("picked_up", "delivered") or (
                status in ("accepted", "preparing", "ready")
                and took <= now
                and random.random() < IN_KITCHEN_WITH_COURIER
            )
            winner = None
            if has_courier:
                in_progress = status != "delivered"
                for i, (cid, vehicle) in enumerate(picks):
                    # Only unfinished deliveries count for the vehicle limit.
                    if not in_progress or active[cid] < VEHICLE_CAPACITY[vehicle]:
                        winner = picks.pop(i)[0]
                        break
                if winner is None and status == "picked_up":
                    # Already picked up: someone must be on it; give it to any car
                    # with room in the city (cars hold 3).
                    for cid, vehicle in couriers:
                        if active[cid] < VEHICLE_CAPACITY[vehicle]:
                            winner = cid
                            break
            if winner is not None:
                if status != "delivered":
                    active[winner] += 1
                offers.append((oid, winner, sent, "accepted"))
                dist = (
                    distance_km(float(rlat), float(rlng), float(dlat), float(dlng))
                    if delivered
                    else None
                )
                deliveries.append((oid, winner, took, picked_up, delivered, dist))
                for cid, _ in picks:
                    offers.append((oid, cid, sent, random.choices(*EXTRA_OUTCOME)[0]))
            elif status == "cancelled":
                # Cancel withdraws the offers still pending (as cancel_order does).
                for cid, _ in picks:
                    offers.append((oid, cid, sent, "withdrawn"))
            elif status in ("accepted", "preparing", "ready"):
                # Still waiting for a courier: pending only inside the 45 s.
                outcome = "pending" if now - sent < ttl else "expired"
                for cid, _ in picks:
                    offers.append((oid, cid, sent, outcome))

        with cur.copy(
            "COPY delivery_offers (order_id, courier_id, sent_at, outcome) FROM STDIN"
        ) as cp:
            for row in offers:
                cp.write_row(row)
        with cur.copy(
            "COPY deliveries (order_id, courier_id, accepted_at, picked_up_at,"
            " delivered_at, distance_km) FROM STDIN"
        ) as cp:
            for row in deliveries:
                cp.write_row(row)
    print(
        f"  couriers={COURIERS} offers={len(offers)} deliveries={len(deliveries)}"
        f" in {time.monotonic() - started:.0f} s"
    )


if __name__ == "__main__":
    main()
