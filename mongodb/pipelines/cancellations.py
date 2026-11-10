"""Pipeline 4: cancellations by reason and by who cancelled, per restaurant, last 90 days."""

from datetime import UTC, datetime, timedelta
from typing import Any

COLLECTION = "report_orders"


def build() -> list[dict[str, Any]]:
    """Per restaurant: orders, cancellations, cancel rate and the (actor, reason) split.

    All orders of the window are read, not only the cancelled ones, so the rate can be
    computed: 10 cancellations mean little without knowing out of how many orders.
    """
    since = datetime.now(UTC) - timedelta(days=90)
    return [
        {"$match": {"placed_at": {"$gte": since}}},
        # 1st group: one bucket per restaurant and (actor, reason). Orders that were
        # not cancelled fall in a bucket with both null: they only count as orders.
        {
            "$group": {
                "_id": {
                    "restaurant_id": "$restaurant_id",
                    "restaurant": "$restaurant_name",
                    "cancelled_by": {
                        "$cond": [
                            {"$eq": ["$status", "cancelled"]},
                            "$cancelled_by",
                            None,
                        ]
                    },
                    "reason": {
                        "$cond": [
                            {"$eq": ["$status", "cancelled"]},
                            "$cancel_reason",
                            None,
                        ]
                    },
                },
                "count": {"$sum": 1},
            }
        },
        # 2nd group: one document per restaurant, with the split as an array.
        {
            "$group": {
                "_id": {
                    "restaurant_id": "$_id.restaurant_id",
                    "restaurant": "$_id.restaurant",
                },
                "orders": {"$sum": "$count"},
                "cancelled": {
                    "$sum": {
                        "$cond": [{"$ne": ["$_id.cancelled_by", None]}, "$count", 0]
                    }
                },
                "split": {
                    "$push": {
                        "cancelled_by": "$_id.cancelled_by",
                        "reason": "$_id.reason",
                        "count": "$count",
                    }
                },
            }
        },
        # Restaurants with no cancellation in the window are not a cancellation report.
        {"$match": {"cancelled": {"$gt": 0}}},
        {
            "$project": {
                "_id": 0,
                "restaurant_id": "$_id.restaurant_id",
                "restaurant": "$_id.restaurant",
                "orders": 1,
                "cancelled": 1,
                "cancel_rate_pct": {
                    "$round": [
                        {"$multiply": [{"$divide": ["$cancelled", "$orders"]}, 100]},
                        1,
                    ]
                },
                # Drop the "not cancelled" bucket and show the biggest causes first.
                "by_actor_and_reason": {
                    "$sortArray": {
                        "input": {
                            "$filter": {
                                "input": "$split",
                                "cond": {"$ne": ["$$this.cancelled_by", None]},
                            }
                        },
                        "sortBy": {"count": -1},
                    }
                },
            }
        },
        # Most cancellations first: the restaurants the back office should look at.
        {"$sort": {"cancelled": -1, "restaurant_id": 1}},
    ]
