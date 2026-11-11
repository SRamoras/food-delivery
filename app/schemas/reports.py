"""Pydantic model for the back-office report response."""

from typing import Any

from pydantic import BaseModel


class ReportResult(BaseModel):
    report: str
    rows: list[dict[str, Any]]
