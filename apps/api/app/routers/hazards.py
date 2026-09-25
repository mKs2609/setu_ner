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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import HazardObservation, IngestRun, SatelliteAcquisition
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


@router.get("/satellite-coverage")
def satellite_coverage(db: Session = Depends(get_db)):
    """When radar last looked at the corridor, and how often it does.

    WHY THIS IS COVERAGE AND NOT FLOOD EXTENT
    Sentinel-1 flood polygons were the plan. Download needs a Copernicus
    account, and turning a 1.7 GB scene into flood boundaries needs a real
    SAR processing pipeline -- see services/ingestion/sources/copernicus.py.
    Producing polygons from a rushed threshold would put flood boundaries on
    a map that nobody could defend, so this reports what can be reported
    honestly.

    It still answers a real question. "Could anything independent have
    confirmed this report?" has a genuine answer, and if the last pass was
    nine days ago that answer is no, whatever a flood pipeline might
    eventually add.

    The cadence is measured from passes we actually recorded, not predicted
    from orbital elements -- we cannot do the latter, and saying so is better
    than implying a forecast.
    """
    rows = db.execute(
        select(SatelliteAcquisition)
        .order_by(SatelliteAcquisition.acquired_at.desc())
        .limit(60)
    ).scalars().all()

    if not rows:
        return {
            "passes_recorded": 0,
            "note": (
                "No coverage recorded yet. Run "
                "`python -m app.services.ingestion.satellite` to populate it."
            ),
        }

    # Several products share one pass (different processing baselines), so
    # distinct acquisition times are what "how often does radar look" means.
    times = sorted({r.acquired_at for r in rows}, reverse=True)
    newest = times[0]
    age_h, status = _age_status(newest)

    gaps = [
        (times[i] - times[i + 1]).total_seconds() / 86400 for i in range(len(times) - 1)
    ]
    gaps = [round(g, 1) for g in gaps if g > 0.1]

    return {
        "passes_recorded": len(times),
        "products_recorded": len(rows),
        "latest_pass_at": newest,
        "hours_since_last_pass": age_h,
        "freshness": status,
        "observed_revisit_days": gaps[:10],
        "typical_revisit_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
        "recent_passes": [
            {
                "name": r.name,
                "product_type": r.product_type,
                "acquired_at": r.acquired_at,
                "size_gb": round(r.size_bytes / 1e9, 2) if r.size_bytes else None,
            }
            for r in rows[:10]
        ],
        "caveats": {
            "coverage_not_flood_extent": (
                "These are radar acquisitions that covered the corridor, not "
                "flood maps. Nothing here says where water is -- only that a "
                "satellite was overhead and a scene exists."
            ),
            "cadence_is_observed": (
                "Revisit days are measured from the passes actually recorded, "
                "not predicted from orbital elements. A gap in our records "
                "looks the same as a gap in coverage."
            ),
            "why_not_flood_extent": (
                "Scene download needs a Copernicus account, and deriving flood "
                "extent needs calibration, speckle filtering, terrain "
                "correction and thresholding. See docs/decisions/0009."
            ),
        },
    }
