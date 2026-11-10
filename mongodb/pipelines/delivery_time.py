"""Pipeline 1: average delivery time (placed to delivered) per zone and hour, last 30 days."""

from datetime import UTC, datetime, timedelta
from typing import Any

COLLECTION = "report_orders"


def build() -> list[dict[str, Any]]:
    """Group delivered orders by customer zone and by the Lisbon hour they were placed."""
    since = datetime.now(UTC) - timedelta(days=30)
    return [
        {"$match": {"status": "delivered", "placed_at": {"$gte": since}}},
        {
            "$group": {
                "_id": {
                    "zone_id": "$customer_zone_id",
                    "zone": "$customer_zone_name",
                    # Lisbon, not UTC: "12h" must mean lunchtime for the business.
                    "hour": {
                        "$hour": {"date": "$placed_at", "timezone": "Europe/Lisbon"}
                    },
                },
                "orders": {"$sum": 1},
                # Subtracting two dates gives milliseconds.
                "avg_ms": {"$avg": {"$subtract": ["$delivered_at", "$placed_at"]}},
            }
        },
        {
            "$project": {
                "_id": 0,
                "zone_id": "$_id.zone_id",
                "zone": "$_id.zone",
                "hour": "$_id.hour",
                "orders": 1,
                "avg_delivery_minutes": {
                    "$round": [{"$divide": ["$avg_ms", 60000]}, 1]
                },
            }
        },
        {"$sort": {"zone": 1, "hour": 1}},
    ]
