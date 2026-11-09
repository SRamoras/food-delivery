"""Imports every model module, so Base.metadata knows every table (Alembic autogenerate).

Add one import per file as the models are written, e.g.:
    from app.models import couriers, orders  # noqa: F401
"""

from app.models import (  # noqa: F401
    couriers,
    customers,
    geo,
    menu,
    orders,
    payments,
    restaurants,
)
