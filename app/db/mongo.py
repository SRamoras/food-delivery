"""MongoDB client (fd_app, readWrite on food_delivery)."""

from pymongo import MongoClient
from pymongo.database import Database

from app.config import settings

# MongoClient keeps its own thread-safe connection pool: create it once and share it.
# tz_aware=True: dates come back as timezone-aware UTC datetimes, never naive ones.
# serverSelectionTimeoutMS: fail after 3 s instead of hanging 30 s when mongo is down.
client: MongoClient = MongoClient(
    settings.mongo_url, tz_aware=True, serverSelectionTimeoutMS=3000
)

# The database named in the URL path (.../food_delivery?authSource=food_delivery).
db: Database = client.get_default_database(default="food_delivery")
