"""Ratings seed: rates about 40% of the delivered orders (COPY).

Runs after B's orders seed (see scripts/seed.sh). Deterministic (random.seed(42)).
restaurant_id is copied from the order: the database does not check that it matches.
    uv run python postgres/seed/ratings.py
"""

import random
import time
from datetime import timedelta

import psycopg

from app.config import settings

random.seed(42)

SHARE = 0.40  # the brief: ratings on about 40% of the delivered orders
# Most customers who rate are happy: 5 and 4 dominate.
SCORES = ([5, 4, 3, 2, 1], [45, 30, 13, 7, 5])
COMMENTS = [
    None,
    None,
    None,
    None,
    "Muito bom!",
    "Chegou frio.",
    "Entrega rápida.",
    "Voltarei a pedir.",
    "Faltou um item.",
    "Simpático e pontual.",
]


def main() -> None:
    start = time.monotonic()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM ratings)")
        if cur.fetchone()[0]:
            print("  ratings already seeded: skipped")
            return
        # The moment each order was delivered, from its status history.
        cur.execute("""
            SELECT o.id, o.restaurant_id, h.changed_at
              FROM orders o
              JOIN order_status_history h
                ON h.order_id = o.id AND h.new_status = 'delivered'
             WHERE o.status = 'delivered'
             ORDER BY o.id
        """)
        rows = [
            (
                order_id,
                restaurant_id,
                random.choices(*SCORES)[0],
                random.choices(*SCORES)[0],
                random.choice(COMMENTS),
                delivered_at + timedelta(minutes=random.randint(10, 180)),
            )
            for order_id, restaurant_id, delivered_at in cur.fetchall()
            if random.random() < SHARE
        ]
        with cur.copy(
            "COPY ratings (order_id, restaurant_id, restaurant_score, courier_score,"
            " comment, created_at) FROM STDIN"
        ) as cp:
            for row in rows:
                cp.write_row(row)
    print(f"  ratings: {len(rows)} in {time.monotonic() - start:.1f} s")


if __name__ == "__main__":
    main()
