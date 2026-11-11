"""Back-office endpoints."""

from fastapi import APIRouter

from app.schemas.reports import ReportResult
from app.services import reports

router = APIRouter(prefix="/backoffice", tags=["backoffice"])


@router.get("/reports/{report_name}")
def get_report(report_name: str) -> ReportResult:
    """Run a report pipeline: delivery-time, cancellations or restaurant-times."""
    return reports.run_report(report_name)
