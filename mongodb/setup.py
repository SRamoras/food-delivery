"""MongoDB setup, run as root: app user, collections, $jsonSchema validators, indexes.

Safe to run any number of times. Run from the repo root:
    uv run python mongodb/setup.py
"""

from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import IndexModel, MongoClient
from pymongo.database import Database

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_NAME = "food_delivery"
APP_USER = "fd_app"


class SetupSettings(BaseSettings):
    # Only what this script needs, so it does not require the app's variables.
    # Real environment variables win over .env (as in app/config.py).
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    mongo_root_url: str
    mongo_app_password: str


def ensure_app_user(db: Database, password: str) -> None:
    """Create fd_app in food_delivery with readWrite on food_delivery only.

    The user lives in food_delivery (hence authSource=food_delivery in MONGO_URL).
    readWrite: find/insert/update/delete and create indexes, but no user or role
    management and no access to any other database (admin included).
    If the user exists, its password and roles are reset, so a password changed in
    .env is applied by re-running setup.
    """
    roles = [{"role": "readWrite", "db": DB_NAME}]
    if db.command("usersInfo", APP_USER)["users"]:
        db.command("updateUser", APP_USER, pwd=password, roles=roles)
        print(f"  user {APP_USER}: updated")
    else:
        db.command("createUser", APP_USER, pwd=password, roles=roles)
        print(f"  user {APP_USER}: created")


def ensure_collection(
    db: Database,
    name: str,
    validator: dict[str, Any],
    indexes: list[IndexModel] | None = None,
) -> None:
    """Create the collection with its validator, or update the validator if it exists.

    validationLevel "strict": every insert and update is validated (also updates to
    documents that were already invalid). validationAction "error": an invalid
    document is refused, not just logged as a warning.
    create_indexes is safe to repeat: an index that already exists with the same
    keys and options is skipped. Changing the options of an existing index (e.g. a
    TTL) fails; drop that index first or change it with collMod.

    Example (C-3):
        ensure_collection(db, "courier_positions",
            {"$jsonSchema": {...}},
            [IndexModel("recorded_at", expireAfterSeconds=604800),
             IndexModel([("courier_id", 1), ("recorded_at", -1)])])
    """
    options = {
        "validator": validator,
        "validationLevel": "strict",
        "validationAction": "error",
    }
    if name in db.list_collection_names():
        db.command("collMod", name, **options)
        action = "validator updated"
    else:
        db.create_collection(name, **options)
        action = "created"
    if indexes:
        db[name].create_indexes(indexes)
    print(f"  collection {name}: {action}, {len(indexes or [])} index(es)")


# One document per position a courier sends (F7). Source of truth for the trail;
# the live position is in Redis (fd:couriers:geo).
COURIER_POSITIONS_VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["courier_id", "location", "recorded_at"],
        # No unknown fields: a typo such as "courierId" is refused, not stored.
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "objectId"},
            # couriers.id in PostgreSQL. pymongo writes a Python int as int or long
            # depending on its size, so both are accepted.
            "courier_id": {"bsonType": ["int", "long"], "minimum": 1},
            # GeoJSON Point, so a 2dsphere index or $geoNear can be added later.
            "location": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "additionalProperties": False,
                "properties": {
                    "type": {"enum": ["Point"]},
                    # GeoJSON order is [longitude, latitude].
                    "coordinates": {
                        "bsonType": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": [
                            {"bsonType": "double", "minimum": -180, "maximum": 180},
                            {"bsonType": "double", "minimum": -90, "maximum": 90},
                        ],
                    },
                },
            },
            # BSON date (not a string): the TTL index only expires date values.
            "recorded_at": {"bsonType": "date"},
            # orders.id, only when the courier is on a delivery (filled from C-4).
            "order_id": {"bsonType": ["int", "long"], "minimum": 1},
        },
    }
}

COURIER_POSITIONS_INDEXES = [
    # TTL: the brief keeps the trail for 7 days (7 * 24 * 3600 = 604800 s).
    # Mongo's TTL monitor runs about once a minute, so expiry is not to the second.
    IndexModel("recorded_at", name="recorded_at_ttl", expireAfterSeconds=604800),
    # "Trail of courier X, newest first": equality on courier_id, then sorted by
    # recorded_at, so the index serves both the filter and the sort.
    IndexModel([("courier_id", 1), ("recorded_at", -1)], name="courier_id_recorded_at"),
]

# report_orders: the fields pipeline 4 (cancellations, B) reads. A self-contained
# sub-schema, so C's report_orders validator includes it with
# {"$jsonSchema": {"allOf": [<C's schema>, REPORT_ORDERS_CANCEL_SCHEMA]}}.
ORDER_STATUSES = [
    "placed",
    "accepted",
    "preparing",
    "ready",
    "picked_up",
    "delivered",
    "cancelled",
    "rejected",
]
# Same lists as the CHECKs on orders in PostgreSQL, so an export bug is refused here.
CANCEL_REASONS = [
    "customer_changed_mind",
    "restaurant_too_busy",
    "item_unavailable",
    "courier_unavailable",
    "payment_issue",
    "other",
]
CANCEL_ACTORS = ["customer", "restaurant", "backoffice"]

REPORT_ORDERS_CANCEL_SCHEMA: dict[str, Any] = {
    "bsonType": "object",
    "required": ["restaurant_id", "restaurant_name", "status", "placed_at"],
    "properties": {
        "restaurant_id": {"bsonType": ["int", "long"], "minimum": 1},
        "restaurant_name": {"bsonType": "string"},
        "status": {"enum": ORDER_STATUSES},
        # BSON dates: the pipeline filters on placed_at (last 90 days).
        "placed_at": {"bsonType": "date"},
        "cancelled_at": {"bsonType": "date"},
        # Also allowed on a rejected order (the restaurant may give a reason).
        "cancel_reason": {"enum": CANCEL_REASONS},
        "cancelled_by": {"enum": CANCEL_ACTORS},
    },
    # As in PostgreSQL: a cancelled order always says who cancelled, why and when;
    # any other order has no cancelled_by. ($jsonSchema has no if/then: oneOf does it.)
    "oneOf": [
        {
            "properties": {"status": {"enum": ["cancelled"]}},
            "required": ["cancelled_by", "cancel_reason", "cancelled_at"],
        },
        {
            "properties": {
                "status": {"enum": [s for s in ORDER_STATUSES if s != "cancelled"]}
            },
            "not": {"required": ["cancelled_by"]},
        },
    ],
}


def main() -> None:
    settings = SetupSettings()
    client: MongoClient = MongoClient(
        settings.mongo_root_url, serverSelectionTimeoutMS=5000
    )
    db = client[DB_NAME]

    ensure_app_user(db, settings.mongo_app_password)

    # --- collections: each owner adds theirs here with ensure_collection ---
    ensure_collection(
        db,
        "courier_positions",
        COURIER_POSITIONS_VALIDATOR,
        COURIER_POSITIONS_INDEXES,
    )
    # C: report_orders, report_offers (B's pipeline 4 fields: REPORT_ORDERS_CANCEL_SCHEMA)

    client.close()


if __name__ == "__main__":
    main()
