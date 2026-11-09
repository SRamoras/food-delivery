"""Daily stock: lazy creation of today's row, the conditional decrement (rule 2) and
its derived copy in Redis."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import LISBON
from app.db.redis import client as redis_client
from app.errors import Conflict
from app.models.orders import Order

# A request still in flight at midnight may write yesterday's key; without a margin
# that key would be born already expired.
STOCK_TTL_MARGIN = timedelta(hours=1)


def stock_key(item_id: int, day: date) -> str:
    """Redis key of one item's stock on one Lisbon day: fd:stock:{item_id}:{yyyy-mm-dd}."""
    # Built only from an int and a date, never from raw request text.
    return f"fd:stock:{item_id}:{day.isoformat()}"


def stock_expire_at(day: date) -> int:
    """Next Lisbon midnight after `day`, plus the margin, as a Unix timestamp for EXAT."""
    midnight = datetime.combine(day + timedelta(days=1), time(0), tzinfo=LISBON)
    return int((midnight + STOCK_TTL_MARGIN).timestamp())


def write_stock_copies(stock_after: dict[int, int], day: date) -> None:
    """Copy PG's `remaining` (from RETURNING) to Redis. Call only after the commit.

    SET with the value PG returned, not DECR in Redis: the copy always mirrors the
    source of truth instead of accumulating its own errors. EXAT goes in the same SET,
    so a key can never be left without an expiry.
    """
    if not stock_after:
        return
    exat = stock_expire_at(day)
    # One round trip for all items; no MULTI needed, each SET stands on its own.
    pipe = redis_client.pipeline(transaction=False)
    for item_id, remaining in stock_after.items():
        pipe.set(stock_key(item_id, day), remaining, exat=exat)
    pipe.execute()


def ensure_today_row(session: Session, item_id: int, day: date) -> None:
    """Lazy reset: the first order of the day creates the row from the configured value.

    ON CONFLICT DO NOTHING: when 60 requests arrive at once, one inserts and the
    others wait on the primary key, then do nothing. No job runs at midnight.
    Items with no configured stock (daily_stock IS NULL) get no row.
    """
    session.execute(
        text("""
            INSERT INTO daily_stock (item_id, stock_date, remaining)
            SELECT id, :day, daily_stock FROM menu_items
             WHERE id = :item AND daily_stock IS NOT NULL
            ON CONFLICT (item_id, stock_date) DO NOTHING
        """),
        {"item": item_id, "day": day},
    )


def take_stock(session: Session, item_id: int, qty: int, day: date) -> int:
    """Check and write in one statement, so two requests cannot both take the last portion.

    The UPDATE locks the row: concurrent requests for the same item queue up. Under
    READ COMMITTED, when the first one commits PostgreSQL re-evaluates the WHERE on
    the new row version; if `remaining` is no longer enough, 0 rows come back → 409.
    Only call it for items with a configured stock (the caller checks daily_stock).

    Returns:
        The portions left after this order.
    """
    ensure_today_row(session, item_id, day)
    remaining = session.execute(
        text("""
            UPDATE daily_stock SET remaining = remaining - :qty
             WHERE item_id = :item AND stock_date = :day AND remaining >= :qty
            RETURNING remaining
        """),
        {"qty": qty, "item": item_id, "day": day},
    ).scalar_one_or_none()
    if remaining is None:
        raise Conflict("sold out")
    return remaining


def take_stock_naive(session: Session, item_id: int, qty: int, day: date) -> int:
    """INTENTIONALLY UNSAFE: read, check in Python, write. Shows the lost update of rule 2.

    Only reachable with ?mode=naive and ENABLE_NAIVE_MODE=true (concurrency test and
    demo). Two requests can both read the same `remaining`, both pass the check, and
    both write the same new value: two orders, one portion taken.
    """
    ensure_today_row(session, item_id, day)
    # No FOR UPDATE, on purpose: other requests read the same value meanwhile.
    current = session.execute(
        text("""
            SELECT remaining FROM daily_stock
             WHERE item_id = :item AND stock_date = :day
        """),
        {"item": item_id, "day": day},
    ).scalar_one()
    if current < qty:
        raise Conflict("sold out")
    new_value = current - qty
    # Absolute value computed in Python: whatever another request wrote between the
    # SELECT and this UPDATE is overwritten (lost update), with no error at all.
    session.execute(
        text("""
            UPDATE daily_stock SET remaining = :new
             WHERE item_id = :item AND stock_date = :day
        """),
        {"new": new_value, "item": item_id, "day": day},
    )
    return new_value


def release_stock(session: Session, order: Order) -> tuple[dict[int, int], date]:
    """Give back the portions of a cancelled or rejected order. Returns PG's new values.

    Runs in the same transaction as the status change, with the order already locked
    (lock_order), so the same order can never give its portions back twice. The
    portions go back to the stock row of the ORDER's Lisbon day, not today's:
    cancelling at 00:10 an order from 23:50 must not inflate the new day's stock.
    Items without a configured stock have no row and are left alone.
    """
    day = order.created_at.astimezone(LISBON).date()
    params = {"o": order.id, "day": day}
    # Lock the stock rows in ascending item_id order, the same order place_order uses,
    # so a cancel and a new order on the same items wait for each other, never deadlock.
    session.execute(
        text("""
            SELECT 1 FROM daily_stock
             WHERE stock_date = :day
               AND item_id IN (SELECT item_id FROM order_lines WHERE order_id = :o)
             ORDER BY item_id
               FOR UPDATE
        """),
        params,
    )
    # One UPDATE for every item; the same item on two lines is added up first.
    rows = session.execute(
        text("""
            UPDATE daily_stock ds SET remaining = ds.remaining + q.qty
              FROM (SELECT item_id, sum(quantity) AS qty
                      FROM order_lines WHERE order_id = :o
                     GROUP BY item_id) q
             WHERE ds.item_id = q.item_id AND ds.stock_date = :day
            RETURNING ds.item_id, ds.remaining
        """),
        params,
    ).all()
    return {item_id: remaining for item_id, remaining in rows}, day
