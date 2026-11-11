"""Exports finished orders and delivery offers from PostgreSQL into the report collections.

Reads with fd_readonly and writes with the app's Mongo user. Safe to re-run: each
collection is emptied and written again, because the reports are derived data.
    uv run python mongodb/export_reports.py
"""

from decimal import Decimal
from typing import Any

from bson.decimal128 import Decimal128
from sqlalchemy import create_engine, text

from app.config import settings
from app.db import mongo

BATCH = 5000  # rows per insert_many: keeps memory flat for 400k orders

# One row per finished order. Lines, cuisines and status dates come from correlated
# subqueries, each served by an index on order_id or restaurant_id.
ORDERS_SQL = text("""
SELECT o.id, o.restaurant_id, r.name AS restaurant_name,
       ci.id AS city_id, ci.name AS city_name,
       rz.id AS restaurant_zone_id, rz.name AS restaurant_zone_name,
       cz.id AS customer_zone_id, cz.name AS customer_zone_name,
       o.status, o.cancel_reason, o.cancelled_by,
       o.subtotal, o.delivery_fee, o.tip, o.total,
       (SELECT array_agg(cu.name ORDER BY cu.name)
          FROM restaurant_cuisines rc JOIN cuisines cu ON cu.id = rc.cuisine_id
         WHERE rc.restaurant_id = o.restaurant_id) AS cuisines,
       (SELECT json_agg(json_build_object(
                   'item_id', l.item_id, 'item_name', l.item_name,
                   'quantity', l.quantity, 'unit_price', l.unit_price::text,
                   'options', l.options) ORDER BY l.id)
          FROM order_lines l WHERE l.order_id = o.id) AS lines,
       (SELECT array_agg(h.new_status ORDER BY h.changed_at)
          FROM order_status_history h WHERE h.order_id = o.id) AS statuses,
       (SELECT array_agg(h.changed_at ORDER BY h.changed_at)
          FROM order_status_history h WHERE h.order_id = o.id) AS changed_at
  FROM orders o
  JOIN restaurants r ON r.id = o.restaurant_id
  JOIN zones rz ON rz.id = r.zone_id
  JOIN zones cz ON cz.id = o.delivery_zone_id
  JOIN cities ci ON ci.id = cz.city_id
 WHERE o.status IN ('delivered', 'cancelled', 'rejected')
 ORDER BY o.id
""")

OFFERS_SQL = text("""
SELECT f.id, f.order_id, f.courier_id, z.id AS zone_id, z.name AS zone_name,
       f.sent_at, f.outcome
  FROM delivery_offers f
  JOIN orders o ON o.id = f.order_id
  JOIN restaurants r ON r.id = o.restaurant_id
  JOIN zones z ON z.id = r.zone_id
 ORDER BY f.id
""")


def money(value: Decimal | str) -> Decimal128:
    """Decimal128 keeps exact cents in Mongo (a float would not)."""
    return Decimal128(Decimal(value))


def order_document(row: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": row.id,
        "restaurant_id": row.restaurant_id,
        "restaurant_name": row.restaurant_name,
        "cuisines": row.cuisines or [],
        "city_id": row.city_id,
        "city_name": row.city_name,
        "restaurant_zone_id": row.restaurant_zone_id,
        "restaurant_zone_name": row.restaurant_zone_name,
        "customer_zone_id": row.customer_zone_id,
        "customer_zone_name": row.customer_zone_name,
        "status": row.status,
        "lines": [
            {**line, "unit_price": money(line["unit_price"])} for line in row.lines
        ],
        "subtotal": money(row.subtotal),
        "delivery_fee": money(row.delivery_fee),
        "tip": money(row.tip),
        "total": money(row.total),
    }
    # Only the fields that apply: a delivered order has no cancel reason.
    if row.cancel_reason is not None:
        doc["cancel_reason"] = row.cancel_reason
    if row.cancelled_by is not None:
        doc["cancelled_by"] = row.cancelled_by
    # placed -> placed_at, picked_up -> picked_up_at, ...
    for status, moment in zip(row.statuses or [], row.changed_at or [], strict=True):
        doc[f"{status}_at"] = moment
    return doc


def offer_document(row: Any) -> dict[str, Any]:
    return {
        "_id": row.id,
        "order_id": row.order_id,
        "courier_id": row.courier_id,
        "zone_id": row.zone_id,
        "zone_name": row.zone_name,
        "sent_at": row.sent_at,
        "outcome": row.outcome,
    }


def export(sql: Any, collection: str, to_document: Any) -> int:
    """Empty the collection and fill it again from PG, BATCH rows at a time."""
    if settings.readonly_database_url is None:
        raise SystemExit("READONLY_DATABASE_URL is not set")
    engine = create_engine(settings.readonly_database_url)
    target = mongo.db[collection]
    target.delete_many({})
    written = 0
    # yield_per: a server-side cursor, so 400k orders never sit in memory at once.
    with engine.connect() as conn:
        result = conn.execution_options(yield_per=BATCH).execute(sql)
        for rows in result.partitions():
            target.insert_many([to_document(row) for row in rows], ordered=False)
            written += len(rows)
    engine.dispose()
    return written


def main() -> None:
    print(f"  report_orders: {export(ORDERS_SQL, 'report_orders', order_document)}")
    print(f"  report_offers: {export(OFFERS_SQL, 'report_offers', offer_document)}")


if __name__ == "__main__":
    main()
