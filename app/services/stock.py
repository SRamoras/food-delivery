"""Daily stock: lazy creation of today's row and the conditional decrement (rule 2)."""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import Conflict


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
