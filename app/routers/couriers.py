"""Courier endpoints: presence and position (F7)."""

from fastapi import APIRouter

from app.schemas.couriers import PositionIn, PresenceOut
from app.services import couriers as service

router = APIRouter(prefix="/couriers/{courier_id}", tags=["couriers"])


@router.post("/online")
def go_online(courier_id: int, body: PositionIn) -> PresenceOut:
    """Go online at the given position (blocked courier → 409)."""
    service.go_online(courier_id, body.lng, body.lat)
    return PresenceOut(courier_id=courier_id, online=True)


@router.post("/position")
def send_position(courier_id: int, body: PositionIn) -> PresenceOut:
    """Send the current position; keeps the courier online for 30 s (offline → 409)."""
    service.send_position(courier_id, body.lng, body.lat)
    return PresenceOut(courier_id=courier_id, online=True)


@router.post("/offline")
def go_offline(courier_id: int) -> PresenceOut:
    """Go offline: removed from the map at once."""
    service.go_offline(courier_id)
    return PresenceOut(courier_id=courier_id, online=False)
