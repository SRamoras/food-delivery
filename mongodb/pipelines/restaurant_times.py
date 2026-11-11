"""Pipeline 5: per restaurant, average time placed to accepted and accepted to ready."""

from typing import Any

COLLECTION = "report_orders"


def build() -> list[dict[str, Any]]:
    """Average both kitchen times per restaurant, over every order it accepted."""
    return [
        {"$match": {"accepted_at": {"$exists": True}}},
        {
            "$group": {
                "_id": {
                    "restaurant_id": "$restaurant_id",
                    "restaurant": "$restaurant_name",
                },
                "orders": {"$sum": 1},
                "avg_accept_ms": {
                    "$avg": {"$subtract": ["$accepted_at", "$placed_at"]}
                },
                # An order cancelled before "ready" has no ready_at: the subtraction is
                # null and $avg skips it, so it still counts for the acceptance time.
                "avg_prepare_ms": {
                    "$avg": {"$subtract": ["$ready_at", "$accepted_at"]}
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "restaurant_id": "$_id.restaurant_id",
                "restaurant": "$_id.restaurant",
                "orders": 1,
                "avg_accept_minutes": {
                    "$round": [{"$divide": ["$avg_accept_ms", 60000]}, 1]
                },
                "avg_prepare_minutes": {
                    "$round": [{"$divide": ["$avg_prepare_ms", 60000]}, 1]
                },
            }
        },
        {"$sort": {"restaurant": 1}},
    ]
