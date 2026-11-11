"""Back-office endpoints: report pipelines and the last-hour ranking."""

from fastapi import APIRouter

from app.schemas.reports import RankedRestaurant, RankingOut, ReportResult
from app.services import ranking, reports

router = APIRouter(prefix="/backoffice", tags=["backoffice"])


@router.get("/reports/{report_name}")
def get_report(report_name: str) -> ReportResult:
    """Run a report pipeline: delivery-time, cancellations or restaurant-times."""
    return reports.run_report(report_name)


@router.get("/cities/{city_id}/ranking")
def get_ranking(city_id: int) -> RankingOut:
    """Top 20 restaurants by deliveries in the last hour, from Redis only."""
    top = ranking.top_restaurants(city_id)
    return RankingOut(
        city_id=city_id,
        restaurants=[RankedRestaurant(restaurant_id=r, deliveries=n) for r, n in top],
    )
