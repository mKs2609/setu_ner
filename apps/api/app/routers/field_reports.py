"""
Field reports: the crowdsourced ground-truth fusion layer.

This is the direct answer to the official PS text's call for the platform
to use "real-time field inputs," not just satellite/telemetry (see
docs/decisions/0001 §4). Reports get fused into the model's belief about an
edge's accessibility, weighted by a reporter trust score.

MVP fusion strategy: simple trust-weighted average on top of the ML
prediction. A proper Bayesian update (each report as a noisy observation
with reporter-specific likelihood) is the natural v2 -- see
app/services/fusion/.
"""

from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class RoadStatus(str, Enum):
    clear = "clear"
    slow = "slow"
    blocked = "blocked"


class FieldReport(BaseModel):
    road_id: str
    status: RoadStatus
    latitude: float
    longitude: float
    note: str | None = None
    photo_url: str | None = None
    reporter_id: str  # anonymous/device-scoped id is fine for MVP; no PII required


class FieldReportResponse(BaseModel):
    id: str
    road_id: str
    status: RoadStatus
    submitted_at: datetime
    reporter_trust_score: float = Field(
        default=0.5, description="Neutral starting trust; adjusted over time by corroboration/contradiction."
    )


@router.post("", response_model=FieldReportResponse)
def submit_field_report(report: FieldReport):
    # TODO: persist to field_reports table, trigger fusion service
    # (app/services/fusion) to update the edge's live accessibility belief.
    return FieldReportResponse(
        id="stub-id",
        road_id=report.road_id,
        status=report.status,
        submitted_at=datetime.now(timezone.utc),
    )


@router.get("/{road_id}")
def get_reports_for_road(road_id: str):
    # TODO: return recent reports for this edge, for the accessibility screen's
    # "field reports" evidence panel
    return {"road_id": road_id, "reports": [], "note": "stub"}
