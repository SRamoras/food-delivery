"""F8 reports: runs a MongoDB aggregation pipeline from mongodb/pipelines/."""

from collections.abc import Callable
from typing import Any

from app.db import mongo
from app.errors import NotFound
from app.schemas.reports import ReportResult
from mongodb.pipelines import cancellations, delivery_time, restaurant_times

# Report name in the URL → (collection, pipeline builder). Pipeline 4 is B's.
REPORTS: dict[str, tuple[str, Callable[[], list[dict[str, Any]]]]] = {
    "delivery-time": (delivery_time.COLLECTION, delivery_time.build),
    "restaurant-times": (restaurant_times.COLLECTION, restaurant_times.build),
    "cancellations": (cancellations.COLLECTION, cancellations.build),
}


def run_report(report_name: str) -> ReportResult:
    """Run the named pipeline on its report collection and return the rows.

    Raises:
        NotFound: no report has that name.
    """
    if report_name not in REPORTS:
        raise NotFound("Report not found")
    collection, build = REPORTS[report_name]
    rows = list(mongo.db[collection].aggregate(build()))
    return ReportResult(report=report_name, rows=rows)
