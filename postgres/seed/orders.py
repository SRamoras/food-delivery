"""Orders seed: 12 months of orders, lines, payments, status history and today's stock (COPY).

Runs after C's catalogue seed and before A's couriers seed (see scripts/seed.sh).
Deterministic (random.seed(42)) and uneven: a few restaurants, customers and items get
most of the orders. Every row respects the constraints; nothing is disabled.
"""

import json
import math
import random
import sys
import time
from bisect import bisect
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import accumulate
from typing import Any

import psycopg

from app.config import LISBON, settings

random.seed(42)

TARGET_ORDERS = 420_000  # the brief asks for >= 400k; some draws are dropped (stock)
DAYS = 365
BATCH = 50_000  # orders per COPY round: keeps memory flat
CENT = Decimal("0.01")

# Line count and quantity weights: about 2.6 lines per order, so >= 1M lines.
LINES_PER_ORDER = ([1, 2, 3, 4, 5], [20, 30, 27, 13, 10])
QUANTITY = ([1, 2, 3], [75, 20, 5])
PAYMENT = (["card", "mbway", "cash"], [55, 30, 15])
TIPS = [Decimal(t) for t in ("0.50", "1.00", "1.50", "2.00", "3.00")]

# How an order ends: ~2% rejected, ~5% cancelled, the rest delivered.
REJECTED, CANCELLED = 0.02, 0.05
# Status an order had reached when cancelled (cancel is only allowed before pickup).
CANCEL_FROM = (["placed", "accepted", "preparing", "ready"], [40, 25, 25, 10])
# Who cancels, and the reasons each actor plausibly gives (pipeline 4 groups by both).
CANCEL_ACTOR = (["customer", "restaurant", "backoffice"], [50, 30, 20])
CANCEL_REASONS = {
    "customer": (["customer_changed_mind", "payment_issue", "other"], [70, 10, 20]),
    "restaurant": (["restaurant_too_busy", "item_unavailable", "other"], [45, 45, 10]),
    "backoffice": (["courier_unavailable", "payment_issue", "other"], [60, 25, 15]),
}
REJECT_REASONS = (["restaurant_too_busy", "item_unavailable"], [60, 40])
FLOW = ["placed", "accepted", "preparing", "ready", "picked_up", "delivered"]


def zipf_cum(n: int, s: float) -> list[float]:
    """Cumulative Zipf weights for n things in a random order: rank k weighs 1/k^s."""
    ranks = list(range(1, n + 1))
    random.shuffle(ranks)
    return list(accumulate(1 / r**s for r in ranks))


def pick(cum: list[float]) -> int:
    """Index drawn from cumulative weights (bisect: O(log n), fast for 1M draws)."""
    return bisect(cum, random.random() * cum[-1])


def load_catalogue(cur: psycopg.Cursor) -> dict[str, Any]:
    """Read what C's seed created: restaurants, hours, fees, addresses and items."""
    cur.execute("SELECT id, zone_id, min_order_value FROM restaurants ORDER BY id")
    restaurants = {r: (z, m) for r, z, m in cur.fetchall()}

    hours: dict[int, dict[int, list[tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    cur.execute(
        "SELECT restaurant_id, weekday, lower(hours), upper(hours) FROM opening_periods"
    )
    for r, wd, lo, hi in cur.fetchall():
        hours[r][wd].append((lo, hi))

    fees: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)
    cur.execute("SELECT restaurant_zone_id, customer_zone_id, fee FROM zone_fees")
    for rz, cz, fee in cur.fetchall():
        fees[rz].append((cz, fee))

    # Addresses grouped by zone, with an uneven weight per customer (heavy users).
    cur.execute(
        """SELECT id, customer_id, street, number, floor, postcode, zone_id, lat, lng, notes
             FROM customer_addresses ORDER BY id"""
    )
    rows = cur.fetchall()
    customer_ids = sorted({row[1] for row in rows})
    # One Pareto weight per customer (not per address), so heavy users stay heavy
    # whichever address is drawn. Capped: customers are drawn inside one zone, and
    # an uncapped Zipf let one customer place 20 orders a day.
    weight = {c: min(random.paretovariate(1.2), 60.0) for c in customer_ids}
    by_zone: dict[int, list[tuple]] = defaultdict(list)
    for row in rows:
        by_zone[row[6]].append(row)
    addresses = {
        z: (lst, list(accumulate(weight[a[1]] for a in lst)))
        for z, lst in by_zone.items()
    }

    cur.execute(
        """SELECT c.restaurant_id, i.id, i.name, i.price, i.options, i.daily_stock
             FROM menu_items i JOIN menu_categories c ON c.id = i.category_id
            WHERE i.status = 'available'
            ORDER BY i.id"""
    )
    items: dict[int, list[tuple]] = defaultdict(list)
    for r, *item in cur.fetchall():
        items[r].append(tuple(item))
    menus = {r: (lst, zipf_cum(len(lst), 1.0)) for r, lst in items.items()}

    # Only restaurants that can really take an order: hours, items, a delivered zone.
    usable = [
        r
        for r, (z, _) in restaurants.items()
        if hours.get(r) and menus.get(r) and any(cz in addresses for cz, _ in fees[z])
    ]
    return {
        "restaurants": restaurants,
        "usable": usable,
        "restaurant_cum": zipf_cum(len(usable), 0.8),
        "hours": hours,
        "fees": fees,
        "addresses": addresses,
        "menus": menus,
    }


def demand(minute: int) -> float:
    """Relative demand by minute of the day: lunch and dinner peaks over a low base."""
    lunch = math.exp(-(((minute - 750) / 50) ** 2))  # ~12:30
    dinner = math.exp(-(((minute - 1200) / 70) ** 2))  # ~20:00
    return 0.12 + lunch + 1.2 * dinner


def order_time(
    periods: dict[int, list[tuple[int, int]]],
    day_cum: list[float],
    today: date,
    now_min: int,
) -> datetime | None:
    """A moment inside the restaurant's opening hours (Lisbon), peaks more likely.

    Today only up to 2 hours ago, so every seeded order is already finished.
    """
    for _ in range(20):
        day = today - timedelta(days=DAYS - 1 - pick(day_cum))
        slots = periods.get(day.weekday())
        if not slots:
            continue
        lo, hi = random.choice(slots)
        if day == today:
            hi = min(hi, now_min - 120)
            if hi <= lo:
                continue
        minute = random.randrange(lo, hi)
        # Rejection sampling: keep the minute with probability demand/max demand.
        if random.random() * 1.35 > demand(minute):
            continue
        h, m = divmod(minute, 60)
        return datetime(
            day.year, day.month, day.day, h, m, random.randrange(60), tzinfo=LISBON
        )
    return None


def choose_options(
    options: list[dict[str, Any]],
) -> tuple[Decimal, list[dict[str, str]]]:
    """Chosen options and their total extra, in the same snapshot shape as pricing.py."""
    extra = Decimal("0.00")
    snapshot = []
    for group in options:
        choices = group.get("choices")
        if not choices or not (group.get("required") or random.random() < 0.3):
            continue
        n = random.randint(1, min(group.get("max", 1), len(choices)))
        for choice in random.sample(choices, n):
            e = Decimal(str(choice.get("extra", 0))).quantize(CENT)
            extra += e
            snapshot.append(
                {"type": group["type"], "name": choice["name"], "extra": str(e)}
            )
    return extra, snapshot


def main() -> None:
    """Generate and load everything in one transaction: a failure leaves no orders."""
    started = time.monotonic()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM orders)")
        if cur.fetchone()[0]:
            # fd_app cannot delete the append-only history, so a second run would
            # only add duplicates: skip instead.
            print("orders already seeded, skipped")
            return
        cat = load_catalogue(cur)
        if not cat["usable"]:
            sys.exit("no usable restaurants: run C's catalogue seed first")

        now = datetime.now(LISBON)
        today = now.date()
        now_min = now.hour * 60 + now.minute
        # Volume grows over the year (+60%), and Friday to Sunday are 25% busier.
        day_weights = []
        for i in range(DAYS):
            d = today - timedelta(days=DAYS - 1 - i)
            day_weights.append(
                (0.8 + 0.6 * i / DAYS) * (1.25 if d.weekday() >= 4 else 1)
            )
        day_cum = list(accumulate(day_weights))

        # Per-restaurant and per-zone speed, so pipelines 1 and 5 have something to show.
        speed = {r: random.uniform(0.7, 1.6) for r in cat["usable"]}
        zone_slowness: dict[int, float] = defaultdict(lambda: random.uniform(0.8, 1.4))

        # When and where: draw every order, then sort by time so ids follow time.
        drafts = []
        for _ in range(TARGET_ORDERS):
            r = cat["usable"][pick(cat["restaurant_cum"])]
            at = order_time(cat["hours"][r], day_cum, today, now_min)
            if at is not None:
                drafts.append((at, r))
        drafts.sort()
        print(
            f"  {len(drafts)} order times drawn in {time.monotonic() - started:.0f} s"
        )

        # Today's stock: only today's row is ever read (lazy reset), so only it is kept.
        stock_today: dict[int, int] = {}
        totals = defaultdict(int)
        for start in range(0, len(drafts), BATCH):
            rows = build_batch(
                cat,
                drafts[start : start + BATCH],
                today,
                speed,
                zone_slowness,
                stock_today,
                totals,
            )
            copy_batch(cur, with_real_ids(cur, rows))
        if stock_today:
            with cur.copy(
                "COPY daily_stock (item_id, stock_date, remaining) FROM STDIN"
            ) as cp:
                for item_id, remaining in stock_today.items():
                    cp.write_row((item_id, today, remaining))
    print(
        f"  orders={totals['orders']} lines={totals['lines']} payments={totals['payments']}"
        f" history={totals['history']} stock_rows={len(stock_today)}"
        f" in {time.monotonic() - started:.0f} s"
    )


def build_batch(
    cat: dict[str, Any],
    drafts: list[tuple[datetime, int]],
    today: date,
    speed: dict[int, float],
    zone_slowness: dict[int, float],
    stock_today: dict[int, int],
    totals: dict[str, int],
) -> dict[str, list[tuple]]:
    """Turn (time, restaurant) drafts into rows for the four tables.

    Orders are numbered 0, 1, 2... inside the batch; with_real_ids swaps in the ids.
    """
    out: dict[str, list[tuple]] = {
        "orders": [],
        "lines": [],
        "payments": [],
        "history": [],
    }
    oid = -1
    for at, r in drafts:
        rest_zone, min_value = cat["restaurants"][r]
        reachable = [
            (cz, fee) for cz, fee in cat["fees"][rest_zone] if cz in cat["addresses"]
        ]
        cust_zone, fee = random.choice(reachable)
        addr_list, addr_cum = cat["addresses"][cust_zone]
        addr = addr_list[pick(addr_cum)]
        customer = addr[1]

        r_roll = random.random()
        outcome = (
            "rejected"
            if r_roll < REJECTED
            else ("cancelled" if r_roll < REJECTED + CANCELLED else "delivered")
        )
        is_today = at.date() == today
        # Stock is taken when placed and given back on cancel/reject, so only
        # delivered orders of today use up today's stock.
        takes_stock = is_today and outcome == "delivered"

        menu, menu_cum = cat["menus"][r]
        n_lines = random.choices(*LINES_PER_ORDER)[0]
        chosen: dict[int, tuple] = {}
        for _ in range(n_lines * 2):  # a few extra draws: popular items repeat
            item = menu[pick(menu_cum)]
            chosen.setdefault(item[0], item)
            if len(chosen) == n_lines:
                break
        lines = []
        for item_id, name, price, options, daily in chosen.values():
            qty = random.choices(*QUANTITY)[0]
            sold_out = (
                takes_stock
                and daily is not None
                and stock_today.get(item_id, daily) < qty
            )
            if sold_out:
                continue  # today's stock is too low: the line is not ordered
            extra, snapshot = choose_options(options or [])
            lines.append(
                [item_id, name, qty, (price + extra).quantize(CENT), snapshot, daily]
            )
        if not lines:
            continue
        subtotal = sum(unit * q for _, _, q, unit, _, _ in lines)
        # Below the restaurant's minimum: one more portion of an unlimited line.
        unlimited = [ln for ln in lines if ln[5] is None]
        while subtotal < min_value and unlimited:
            ln = min(unlimited, key=lambda x: x[3])
            ln[2] += 1
            subtotal += ln[3]
        if subtotal < min_value:
            continue
        tip = Decimal("0.00") if random.random() < 0.7 else random.choice(TIPS)
        total = subtotal + fee + tip

        oid += 1
        # The order is kept: only now does it take today's stock (a dropped order
        # must not use up portions).
        if takes_stock:
            for item_id, _, qty, _, _, daily in lines:
                if daily is not None:
                    stock_today[item_id] = stock_today.get(item_id, daily) - qty
        # Timeline: each step a few minutes after the last, slower at peak hours
        # (Lisbon lunch and dinner).
        peak = 1.3 if 720 <= at.hour * 60 + at.minute <= 840 or at.hour >= 19 else 1.0
        # Then UTC: adding minutes to a Lisbon time adds wall-clock minutes, which
        # goes backwards on the night the clocks change.
        at = at.astimezone(UTC)
        s = speed[r]
        steps = {
            "placed": at,
            "accepted": at + timedelta(minutes=random.uniform(1, 6) * s),
        }
        steps["preparing"] = steps["accepted"] + timedelta(
            minutes=random.uniform(0.5, 3)
        )
        steps["ready"] = steps["preparing"] + timedelta(
            minutes=random.triangular(8, 35, 15) * s * peak
        )
        steps["picked_up"] = steps["ready"] + timedelta(minutes=random.uniform(2, 10))
        steps["delivered"] = steps["picked_up"] + timedelta(
            minutes=random.uniform(6, 22) * zone_slowness[cust_zone] * peak
        )

        who = {
            "placed": ("customer", customer),
            "accepted": ("restaurant", r),
            "preparing": ("restaurant", r),
            "ready": ("restaurant", r),
            # Couriers are seeded after orders (A's seed), so the id is unknown here.
            "picked_up": ("courier", None),
            "delivered": ("courier", None),
        }
        cancel_reason = cancelled_by = None
        if outcome == "delivered":
            reached = FLOW
            end = steps["delivered"]
        elif outcome == "rejected":
            reached = ["placed"]
            end = at + timedelta(minutes=random.uniform(1, 5))
            cancel_reason = random.choices(*REJECT_REASONS)[0]
        else:
            last = random.choices(*CANCEL_FROM)[0]
            reached = FLOW[: FLOW.index(last) + 1]
            end = steps[last] + timedelta(minutes=random.uniform(1, 8))
            cancelled_by = random.choices(*CANCEL_ACTOR)[0]
            cancel_reason = random.choices(*CANCEL_REASONS[cancelled_by])[0]

        prev = None
        for st in reached:
            out["history"].append((oid, prev, st, *who[st], steps[st]))
            prev = st
        if outcome == "rejected":
            out["history"].append((oid, "placed", "rejected", "restaurant", r, end))
        elif outcome == "cancelled":
            actor_id = {"customer": customer, "restaurant": r}.get(cancelled_by)
            out["history"].append((oid, prev, "cancelled", cancelled_by, actor_id, end))

        out["orders"].append(
            (
                oid,
                customer,
                r,
                addr[0],
                addr[2],
                addr[3],
                addr[4],
                addr[5],
                addr[6],
                addr[7],
                addr[8],
                addr[9],
                subtotal,
                fee,
                tip,
                total,
                outcome,
                cancel_reason,
                cancelled_by,
                at,
            )
        )
        for item_id, name, qty, unit, snapshot, _ in lines:
            out["lines"].append((oid, item_id, name, qty, unit, json.dumps(snapshot)))
        method = random.choices(*PAYMENT)[0]
        # provider_ref is added by with_real_ids: it is built from the real order id.
        out["payments"].append((oid, total, method, "approved", at))
        # Rejected and cancelled orders paid online get their money back.
        if outcome != "delivered" and method != "cash":
            out["payments"].append((oid, total, method, "refunded", end))

    for key, rows in out.items():
        totals[key] += len(rows)
    return out


def with_real_ids(
    cur: psycopg.Cursor, rows: dict[str, list[tuple]]
) -> dict[str, list[tuple]]:
    """Replace the batch-local order numbers with ids taken from orders_id_seq.

    nextval, not explicit ids + setval: fd_app may use the sequence but not set it,
    and ids from the sequence never clash with orders placed later through the API.
    """
    cur.execute(
        "SELECT nextval('orders_id_seq') FROM generate_series(1, %s)",
        (len(rows["orders"]),),
    )
    ids = [row[0] for row in cur.fetchall()]
    # Every table starts with the order number (orders.id or order_id).
    real = {key: [(ids[row[0]], *row[1:]) for row in lst] for key, lst in rows.items()}
    # Unique provider reference per online payment (cash has none, as the CHECK says):
    # one approved and at most one refund per order, so the id makes it unique.
    real["payments"] = [
        (
            *p,
            None
            if p[2] == "cash"
            else f"seed_{'rf_' if p[3] == 'refunded' else ''}{p[0]}",
        )
        for p in real["payments"]
    ]
    return real


def copy_batch(cur: psycopg.Cursor, rows: dict[str, list[tuple]]) -> None:
    """Bulk load one batch with COPY: far faster than INSERTs for millions of rows."""
    copies = [
        (
            """COPY orders (id, customer_id, restaurant_id, source_address_id,
                delivery_street, delivery_number, delivery_floor, delivery_postcode,
                delivery_zone_id, delivery_lat, delivery_lng, delivery_notes, subtotal,
                delivery_fee, tip, total, status, cancel_reason, cancelled_by, created_at)
            FROM STDIN""",
            "orders",
        ),
        (
            """COPY order_lines (order_id, item_id, item_name, quantity, unit_price, options)
            FROM STDIN""",
            "lines",
        ),
        (
            """COPY payments (order_id, amount, method, status, paid_at, provider_ref)
            FROM STDIN""",
            "payments",
        ),
        (
            """COPY order_status_history (order_id, old_status, new_status, actor_type,
                actor_id, changed_at) FROM STDIN""",
            "history",
        ),
    ]
    for sql, key in copies:
        with cur.copy(sql) as cp:
            for row in rows[key]:
                cp.write_row(row)


if __name__ == "__main__":
    main()
