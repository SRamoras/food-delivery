"""Order life cycle: place (F2) and, later, status updates (F5)."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import LISBON
from app.errors import Conflict, NotFound
from app.models.orders import Order, OrderLine
from app.models.payments import Payment
from app.schemas.orders import PlaceOrderIn
from app.services import stock
from app.services.order_status import check_transition, record_status
from app.services.pricing import price_line


@dataclass
class PlacedOrder:
    order: Order
    stock_date: date
    # item_id -> portions left (from RETURNING), written to Redis after the commit.
    stock_after: dict[int, int] = field(default_factory=dict)


def place_order(session: Session, customer_id: int, body: PlaceOrderIn) -> PlacedOrder:
    """Place an order in the caller's transaction. Any Conflict/NotFound rolls it all back.

    Writes the order, its lines, the approved payment and the first history row, and
    takes the daily stock. Only the stock must be exact under concurrency, so only it
    is protected (conditional UPDATE in stock.take_stock); the other checks are reads.
    """
    # 1. Simulated payment declined: refuse before writing anything.
    if body.simulate == "declined":
        raise Conflict("payment declined")

    # 2. The address must belong to this customer (404, as if it did not exist).
    addr = (
        session.execute(
            text("""
                SELECT id, street, number, floor, postcode, zone_id, lat, lng, notes
                  FROM customer_addresses
                 WHERE id = :a AND customer_id = :c
            """),
            {"a": body.address_id, "c": customer_id},
        )
        .mappings()
        .one_or_none()
    )
    if addr is None:
        raise NotFound("address not found for this customer")

    # Items are read first only to learn the restaurant. Items have no restaurant_id:
    # they belong to a category, and the category to the restaurant.
    item_ids = sorted({line.item_id for line in body.lines})
    items = {
        row["id"]: row
        for row in session.execute(
            text("""
                SELECT i.id, c.restaurant_id, i.name, i.price, i.status, i.options,
                       i.daily_stock
                  FROM menu_items i
                  JOIN menu_categories c ON c.id = i.category_id
                 WHERE i.id = ANY(:ids)
            """),
            {"ids": item_ids},
        ).mappings()
    }
    if len(items) != len(item_ids):
        raise Conflict("some items do not exist")
    restaurant_ids = {row["restaurant_id"] for row in items.values()}
    if len(restaurant_ids) != 1:
        raise Conflict("all items must be from the same restaurant")
    restaurant_id = restaurant_ids.pop()

    # 3. Restaurant open, inside its hours now (Lisbon time), delivering to the zone.
    now = datetime.now(LISBON)
    rest = (
        session.execute(
            text(
                "SELECT status, zone_id, min_order_value FROM restaurants WHERE id = :r"
            ),
            {"r": restaurant_id},
        )
        .mappings()
        .one()
    )
    if rest["status"] != "open":
        raise Conflict("restaurant is not open")
    # weekday(): 0 = Monday, the same convention as opening_periods.weekday.
    # hours is an int4range of minutes of the day, [0,1440) = 00:00 to 24:00.
    # CAST: psycopg sends small Python ints as smallint, and there is no
    # int4range @> smallint operator.
    in_hours = session.execute(
        text("""
            SELECT 1 FROM opening_periods
             WHERE restaurant_id = :r AND weekday = :wd
               AND hours @> CAST(:m AS integer)
             LIMIT 1
        """),
        {"r": restaurant_id, "wd": now.weekday(), "m": now.hour * 60 + now.minute},
    ).first()
    if in_hours is None:
        raise Conflict("restaurant is closed at this time")
    # No zone_fees row for the pair means the restaurant does not deliver there.
    fee = session.execute(
        text("""
            SELECT fee FROM zone_fees
             WHERE restaurant_zone_id = :rz AND customer_zone_id = :cz
        """),
        {"rz": rest["zone_id"], "cz": addr["zone_id"]},
    ).scalar_one_or_none()
    if fee is None:
        raise Conflict("restaurant does not deliver to this address")

    # 4. Every item available.
    if any(row["status"] != "available" for row in items.values()):
        raise Conflict("some items are not available")

    # 5. Prices with options; the subtotal must reach the restaurant's minimum.
    priced = []
    for line in body.lines:
        item = items[line.item_id]
        unit, snapshot = price_line(item["price"], item["options"] or [], line.options)
        priced.append((line, unit, snapshot))
    subtotal = sum((unit * line.quantity for line, unit, _ in priced), Decimal("0.00"))
    if subtotal < rest["min_order_value"]:
        raise Conflict("order is below the restaurant's minimum")
    delivery_fee = Decimal(fee)
    total = subtotal + delivery_fee + body.tip

    # 6. Stock, only for items with a configured limit. Same item on two lines is
    # added up. Ascending item_id: two orders that share items lock their stock rows
    # in the same order, so they wait for each other instead of deadlocking.
    qty: dict[int, int] = defaultdict(int)
    for line in body.lines:
        if items[line.item_id]["daily_stock"] is not None:
            qty[line.item_id] += line.quantity
    stock_after = {
        item_id: stock.take_stock(session, item_id, qty[item_id], now.date())
        for item_id in sorted(qty)
    }

    # 7. Order (with the address snapshot), lines, approved payment, history.
    check_transition(None, "placed", "customer")
    order = Order(
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        source_address_id=addr["id"],
        delivery_street=addr["street"],
        delivery_number=addr["number"],
        delivery_floor=addr["floor"],
        delivery_postcode=addr["postcode"],
        delivery_zone_id=addr["zone_id"],
        delivery_lat=addr["lat"],
        delivery_lng=addr["lng"],
        delivery_notes=addr["notes"],
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tip=body.tip,
        total=total,
        status="placed",
    )
    session.add(order)
    # flush sends the INSERT inside the transaction (no commit) to get order.id.
    session.flush()
    session.add_all(
        OrderLine(
            order_id=order.id,
            item_id=line.item_id,
            item_name=items[line.item_id]["name"],
            quantity=line.quantity,
            unit_price=unit,
            options=snapshot,
        )
        for line, unit, snapshot in priced
    )
    # Cash has no provider; card and MB WAY get a unique simulated reference.
    session.add(
        Payment(
            order_id=order.id,
            amount=total,
            method=body.payment_method,
            status="approved",
            provider_ref=None
            if body.payment_method == "cash"
            else f"sim_{uuid4().hex}",
        )
    )
    record_status(session, order.id, None, "placed", "customer", customer_id)
    return PlacedOrder(order=order, stock_date=now.date(), stock_after=stock_after)
