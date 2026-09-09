"""
Field reports: the crowdsourced ground-truth layer.

This is the direct answer to the problem statement's call for the platform to
use real-time field inputs, not just satellite and telemetry (see
docs/decisions/0001 section 4). Official telemetry across the NER is sparse,
so human reports are how the data gap actually gets filled.

WHAT THE ENDPOINTS PROMISE

  POST /field-reports          Record what someone saw. Snapped to the nearest
                               road, stored verbatim, never overwriting anything.
  GET  /field-reports/recent   The latest reports across the corridor.
  GET  /field-reports/road/{id}  Every recent report on one road, plus the
                               fused view of what they collectively say.

WHAT THEY DO NOT DO
Nothing here writes `roads.current_accessibility`. That column is reserved
for the Phase 3 model and stays empty. The fused status is published as its
own field with its own confidence, so a reader can always tell a crowd
consensus from a model prediction. See services/fusion/reports.py.
"""

from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import FieldReport, Road
from app.db.session import get_db
from app.services.fusion import corroboration as corrob
from app.services.fusion import reports as fusion

router = APIRouter()

# Not security -- an opaque reporter id is trivially rotated -- but it stops a
# retry loop or one enthusiastic client from burying a road in duplicates.
MAX_REPORTS_PER_HOUR = 30


class RoadStatus(str, Enum):
    clear = "clear"
    slow = "slow"
    blocked = "blocked"


class FieldReportIn(BaseModel):
    status: RoadStatus
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    reporter_id: str = Field(
        min_length=6,
        max_length=128,
        description=(
            "Opaque, device-scoped id the client generates and keeps. Not a "
            "name, phone number or account -- no personal data is wanted here."
        ),
    )
    note: str | None = Field(None, max_length=500)


class FieldReportOut(BaseModel):
    id: int
    road_id: int | None
    status: RoadStatus
    submitted_at: datetime
    snapped_distance_m: float | None
    counted_in_fusion: bool
    reporter_trust_score: float
    trust_outcome: str
    trust_basis: str
    trust_explanation: str
    independent_evidence: dict
    note: str | None = None


def road_district(db: Session, road_id: int | None) -> str | None:
    """The district a road sits in, for matching district-level evidence."""
    if road_id is None:
        return None
    road = db.get(Road, road_id)
    return road.district if road else None


def _serialise(report: FieldReport) -> dict:
    point = to_shape(report.geometry)
    return {
        "id": report.id,
        "road_id": report.road_id,
        "status": report.status,
        "note": report.note,
        "submitted_at": report.submitted_at,
        "snapped_distance_m": (
            round(report.snapped_distance_m, 1)
            if report.snapped_distance_m is not None
            else None
        ),
        "trust_at_submission": report.trust_at_submission,
        "longitude": point.x,
        "latitude": point.y,
    }


@router.post("", response_model=FieldReportOut)
def submit_field_report(payload: FieldReportIn, db: Session = Depends(get_db)):
    """Record one observation from the ground."""
    if fusion.reports_in_last_hour(db, payload.reporter_id) >= MAX_REPORTS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=(
                f"More than {MAX_REPORTS_PER_HOUR} reports in the last hour from "
                f"this reporter id. Slow down, or check for a retry loop."
            ),
        )

    snap = fusion.snap_to_road(db, payload.longitude, payload.latitude)
    reporter = fusion.get_or_create_reporter(db, payload.reporter_id)

    report = FieldReport(
        road_id=snap.road_id,
        snapped_distance_m=snap.distance_m,
        status=payload.status.value,
        note=payload.note,
        geometry=func.ST_SetSRID(
            func.ST_MakePoint(payload.longitude, payload.latitude), 4326
        ),
        reporter_id=reporter.id,
        # Frozen deliberately: trust moves later, and freezing it here is what
        # keeps an old fused result reproducible.
        trust_at_submission=reporter.trust_score,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(report)
    reporter.reports_submitted += 1
    db.commit()
    db.refresh(report)

    # Independent evidence is checked before trust moves, because it can
    # override a peer disagreement -- see services/fusion/corroboration.py.
    evidence = corrob.corroborate(
        db,
        road_id=report.road_id,
        district=road_district(db, report.road_id),
        status=report.status,
    )
    trust = fusion.update_trust(
        db, reporter, report, independently_supported=evidence.supports
    )
    db.commit()

    return FieldReportOut(
        id=report.id,
        road_id=report.road_id,
        status=payload.status,
        submitted_at=report.submitted_at,
        snapped_distance_m=(
            round(snap.distance_m, 1) if snap.distance_m is not None else None
        ),
        counted_in_fusion=snap.within_range,
        reporter_trust_score=trust.trust_score,
        trust_outcome=trust.outcome,
        trust_basis=trust.basis,
        trust_explanation=trust.explanation,
        independent_evidence=evidence.as_dict(),
        note=report.note,
    )


@router.get("/recent")
def recent_reports(
    limit: int = Query(50, le=500),
    status: RoadStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    """Latest reports across the corridor, newest first."""
    stmt = select(FieldReport).order_by(FieldReport.submitted_at.desc())
    if status:
        stmt = stmt.where(FieldReport.status == status.value)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return {
        "count": len(rows),
        "reports": [_serialise(r) for r in rows],
        "note": (
            "A report with road_id null landed further than "
            f"{fusion.MAX_SNAP_DISTANCE_M:.0f} m from any road in the corridor. "
            "It is kept, but excluded from fusion -- discarding it would hide "
            "that somebody is reporting from an area we do not cover."
        ),
    }


@router.get("/road/{road_id}")
def reports_for_road(road_id: int, db: Session = Depends(get_db)):
    """Every recent report on one road, and what they collectively say."""
    road = db.get(Road, road_id)
    if road is None:
        raise HTTPException(status_code=404, detail=f"Road {road_id} not found")

    rows = fusion.recent_reports(db, road_id)
    fused = fusion.fuse(db, road_id)
    evidence = corrob.corroborate(
        db,
        road_id=road_id,
        district=road.district,
        status=fused.status or "blocked",
    )

    return {
        "road_id": road_id,
        "road": {
            "name": road.name,
            "road_class": road.road_class,
            "district": road.district,
            "is_bridge": road.is_bridge,
            "baseline_accessibility": road.baseline_accessibility,
        },
        "field_reported": {
            "status": fused.status,
            "confidence": fused.confidence,
            "report_count": fused.report_count,
            "weight_by_status": fused.weight_by_status,
            "newest_report_at": fused.newest_report_at,
            "window_hours": fused.window_hours,
        },
        "independent_evidence": evidence.as_dict(),
        "reports": [_serialise(r) for r in rows],
        "caveats": {
            "not_a_model_prediction": (
                "field_reported is a trust-weighted vote of what people on the "
                "ground reported in the last "
                f"{fusion.FUSION_WINDOW_HOURS} hours. It is NOT a model output, "
                "and it is deliberately not written into current_accessibility, "
                "which stays empty until the Phase 3 model exists."
            ),
            "collusion": (
                "Peer agreement alone can be manufactured by a group reporting "
                "together. Reports are therefore also checked against DRIMS "
                "hazard data, which nobody submitting reports controls, and "
                "independent support outranks peer disagreement. See "
                "docs/decisions/0006-corroboration.md."
            ),
            "baseline_is_historical": (
                "baseline_accessibility comes from 2025 district flood severity, "
                "not from these reports. The two are separate on purpose."
            ),
        },
    }
