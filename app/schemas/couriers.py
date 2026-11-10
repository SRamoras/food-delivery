"""Request and response bodies for the courier endpoints."""

from pydantic import BaseModel, Field


class PositionIn(BaseModel):
    # Ranges checked here, so Redis never gets a coordinate GEOADD would refuse.
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-85.05112878, le=85.05112878)


class PresenceOut(BaseModel):
    courier_id: int
    online: bool
