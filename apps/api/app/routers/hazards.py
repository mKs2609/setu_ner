"""
Hazard observations and, just as importantly, how stale they are.

HAZARD-AGNOSTIC BY DESIGN (docs/decisions/0001 section 3)
`hazard_type` and `metric` carry the meaning, so a landslide or rainfall row
is served by the same endpoint as a flood row with no schema change. The
DRIMS source already publishes nine hazard types behind one endpoint.

WHY /freshness EXISTS AND IS NOT OPTIONAL
The gap analysis asked for staleness tracking "from day one" rather than
bolted on later, and this is the reason: ingestion never deletes, so when a
source goes down the most recent observation simply stops moving. Without an
explicit age, a three-week-old "0 roads damaged" reads exactly like a live
all-clear. That is the most dangerous possible failure for a tool someone
might route relief convoys with.

So the age of the data is a first-class response field, every list response
carries the freshness of what it just returned, and a caller that ignores it
has to do so deliberately.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import HazardObservation, IngestRun
from app.db.session import get_db

router = APIRouter()

# A daily report published once a day. One missed day is unremarkable; two
# means something is wrong. Expressed in hours so the boundary is visible
# rather than buried in a comparison.
FRESH_HOURS = 36
STALE_HOURS = 72


def _age_status(observed_at: datetime | None) -> tuple[float | None, str]:
    if observed_at is None:
        return None, "unknown"
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - observed_at).total_seconds() / 3600
    if age_h <= FRESH_HOURS:
        status = "fresh"
    elif age_h <= STALE_HOURS:
        status = "stale"
    else:
        status = "very_stale"
    return round(age_h, 1), status


@router.get("/freshness")
def freshness(db: Session = Depends(get_db)):
    """How old the newest observation is, per source and hazard type.

    Read this before trusting anything from the list endpoint.
    """
    rows = db.execute(
        select(
            HazardObservation.source,
            HazardObservation.hazard_type,
            func.max(HazardObservation.observed_at),
            func.max(HazardObservation.fetched_at),
            func.count(HazardObservation.id),
        ).group_by(HazardObservation.source, HazardObservation.hazard_type)
    ).all()

    sources = []
    for source, hazard_type, latest_observed, latest_fetched, count in rows:
        age_h, status = _age_status(latest_observed)
        sources.append(
            {
                "source": source,
                "hazard_type": hazard_type,
                "latest_observed_at": latest_observed,
                "latest_fetched_at": latest_fetched,
                "age_hours": age_h,
                "status": status,
                "observation_count": count,
            }
        )

    recent_runs = db.execute(
        select(IngestRun).order_by(IngestRun.started_at.desc()).limit(10)
    ).scalars().all()

    return {
        "sources": sources,
        "recent_runs": [
            {
                "id": r.id,
                "source": r.source,
                "hazard_type": r.hazard_type,
                "target_date": r.target_date,
                "status": r.status,
                "started_at": r.started_at,
                "rows_written": r.rows_written,
                "rows_duplicate": r.rows_duplicate,
                "error": r.error,
            }
            for r in recent_runs
        ],
        "thresholds": {"fresh_within_hours": FRESH_HOURS, "stale_after_hours": STALE_HOURS},
        "note": (
            "Ingestion only ever inserts -- it never deletes or blanks earlier "
            "observations. So a source going down shows up here as rising "
            "age_hours plus a failed run, never as an empty result that could "
            "be mistaken for an all-clear."
        ),
    }


@router.get("")
def list_hazards(
    hazard_type: str | None = Query(None, description="e.g. 'flood'"),
    district: str | None = Query(None, description="Normalised name, e.g. 'Cachar'"),
    metric: str | None = Query(None, description="e.g. 'roads_damaged'"),
    since: str | None = Query(None, description="ISO date; observations on or after it"),
    corridor_only: bool = Query(
        False, description="Only districts the road graph actually covers"
    ),
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
):
    """Hazard observations, newest first, with the freshness of what matched."""
    stmt = select(HazardObservation).order_by(HazardObservation.observed_at.desc())
    if hazard_type:
        stmt = stmt.where(HazardObservation.hazard_type == hazard_type)
    if district:
        stmt = stmt.where(HazardObservation.district == district)
    if metric:
        stmt = stmt.where(HazardObservation.metric == metric)
    if corridor_only:
        stmt = stmt.where(HazardObservation.district.isnot(None))
    if since:
        stmt = stmt.where(
            HazardObservation.observed_at
            >= datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
        )

    rows = db.execute(stmt.limit(limit)).scalars().all()
    newest = max((r.observed_at for r in rows if r.observed_at), default=None)
    age_h, status = _age_status(newest)

    return {
        "count": len(rows),
        "freshness": {
            "newest_observed_at": newest,
            "age_hours": age_h,
            "status": status,
        },
        "observations": [
            {
                "id": r.id,
                "hazard_type": r.hazard_type,
                "metric": r.metric,
                "value_num": r.value_num,
                "value_text": r.value_text,
                "unit": r.unit,
                "place_name": r.place_name,
                "district": r.district,
                "observed_at": r.observed_at,
                "fetched_at": r.fetched_at,
                "source": r.source,
                "source_url": r.source_url,
                "basis": r.basis,
                "confidence": r.confidence,
            }
            for r in rows
        ],
        "note": (
            "district is our normalised name; place_name is exactly what the "
            "source printed. They differ where Assam has renamed a district -- "
            "the source says Sribhumi, the road graph still says Karimganj."
        ),
    }
