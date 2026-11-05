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


def main() -> None:
    settings = SetupSettings()
    client: MongoClient = MongoClient(
        settings.mongo_root_url, serverSelectionTimeoutMS=5000
    )
    db = client[DB_NAME]

    ensure_app_user(db, settings.mongo_app_password)

    # --- collections: each owner adds theirs here with ensure_collection ---
    # A: courier_positions (C-3)
    # C: report_orders, report_offers (B adds the pipeline 4 fields)

    client.close()


if __name__ == "__main__":
    main()
