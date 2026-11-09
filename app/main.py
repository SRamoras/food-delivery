"""FastAPI application: routers, exception handlers and the health check."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import mongo, postgres, redis
from app.errors import register_exception_handlers
from app.routers import couriers, customers, orders, restaurants

app = FastAPI(title="Food delivery API")
register_exception_handlers(app)

# Routers are included here as each slice adds them, e.g.:
# from app.routers import couriers
# app.include_router(couriers.router)
app.include_router(orders.router)
# Routers are included here as each slice adds them.
app.include_router(couriers.router)
app.include_router(customers.router)
app.include_router(restaurants.router)


# `def`, not `async def`: FastAPI runs it in a thread pool, like every endpoint that
# uses the sync drivers.
@app.get("/health")
def health() -> JSONResponse:
    """Ping PostgreSQL, MongoDB and Redis: 200 if all answer, 503 otherwise."""
    checks: dict[str, str] = {}

    try:
        with postgres.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except SQLAlchemyError as exc:  # report every database, not just the first error
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        mongo.db.command("ping")
        checks["mongo"] = "ok"
    except PyMongoError as exc:
        checks["mongo"] = f"error: {type(exc).__name__}"

    try:
        redis.client.ping()
        checks["redis"] = "ok"
    except RedisError as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", **checks},
    )
