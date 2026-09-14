"""
What the Phase 3 model is, how good it is, and whether that is still true.

    GET /api/v1/model/status      evaluation, live track record, caveats
    GET /api/v1/model/districts   the latest district forecasts

The status endpoint exists because a probability without a track record is
an assertion. It returns the held-out season's numbers next to the baselines
they have to beat, and -- as forecasts made in production reach their target
day -- scores those too, so the claim is re-checked by reality rather than
frozen at training time.
"""

from __future__ import annotations

from datetime import date

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DistrictFloodForecast, Road, RoadDamageMatch
from app.services.explain import forecast as forecast_explain
from app.services.ingestion.districts import normalise_district
from app.services.model.dataset import district_key, features_for
from app.db.session import get_db
from app.services.model import district_model as dm
from app.services.model import score as scoring
from app.services.model.history import load_history

router = APIRouter()

CAVEATS = {
    "what_is_predicted": (
        "Whether a district appears as flood-affected in the next DRIMS Assam daily "
        "report(s). Not whether a particular road is passable."
    ),
    "per_road_is_a_prior": (
        "Per-road values multiply the district probability by a terrain exposure "
        "prior (height above the district's low ground). That prior is a stated "
        "assumption, not fitted: the corridor has too few geolocated road-damage "
        "reports to fit or validate it."
    ),
    "no_rainfall": (
        "The model has no rainfall input. Every free daily source tried disallows "
        "automated access, so a flood becomes visible to it only once reported. "
        "Onset skill is expected to be weak, and is reported separately."
    ),
    "damage_dates": (
        "DRIMS damage rows are dated when reported, sometimes weeks after the damage, "
        "which is why road damage is not the prediction target."
    ),
    "trained_statewide": (
        "Trained on every Assam district, because the four corridor districts alone "
        "provide too few flood onsets to learn from."
    ),
}


def _artifact_summary(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    return {
        "version": payload["version"],
        "horizon_days": payload["horizon_days"],
        "served_kind": payload["kind"],
        "trained_at": payload["trained_at"],
        "train_period": payload["train_period"],
        "test_period": payload["test_period"],
        "selection": payload["selection"],
        "test_metrics": payload["test_metrics"],
        "verdict": payload["verdict"],
        "features": payload["features"],
        "params": payload["params"],
    }


def _live_track_record(db: Session, history) -> dict:
    """Score stored forecasts whose target day now has a published report."""
    published = set(history.published)
    rows = db.execute(select(DistrictFloodForecast)).scalars().all()
    by_h: dict[int, list] = {}
    for f in rows:
        if f.target_date not in published:
            continue
        outcome = history.state(f.district_key, f.target_date)
        if outcome is None:
            continue
        by_h.setdefault(f.horizon_days, []).append(
            (int(outcome.affected), f.probability, f.persistence_probability)
        )

    out = {}
    for h in dm.HORIZONS:
        items = by_h.get(h, [])
        if not items:
            out[str(h)] = {"n": 0, "note": "no live forecast has reached its target day yet"}
            continue
        y = np.asarray([i[0] for i in items])
        served = dm.score(y, np.asarray([i[1] for i in items]))
        pers = dm.score(y, np.asarray([i[2] for i in items]))
        out[str(h)] = {
            "n": served["n"],
            "served": served,
            "persistence": pers,
            "skill_vs_persistence": (
                round(1 - served["brier"] / pers["brier"], 4) if pers.get("brier") else None
            ),
        }
    return out


def _exposure_check(db: Session) -> dict:
    """Where do matched damage reports sit on the exposure prior?

    If the prior means anything, damaged roads should skew toward high
    exposure. With a handful of matches this cannot confirm the prior; it is
    reported so that the day it contradicts the prior is visible.
    """
    rows = db.execute(
        select(Road.hazard_exposure, RoadDamageMatch.quality)
        .join(Road, Road.id == RoadDamageMatch.road_id)
        .where(RoadDamageMatch.quality.in_(["confident", "approximate"]))
    ).all()
    exposures = [e for e, _ in rows if e is not None]
    corridor_mean = db.execute(
        select(func.avg(Road.hazard_exposure)).where(Road.hazard_exposure.isnot(None))
    ).scalar()
    return {
        "matched_damage_reports": len(rows),
        "with_exposure": len(exposures),
        "mean_exposure_of_damaged_roads": (
            round(float(np.mean(exposures)), 3) if exposures else None
        ),
        "mean_exposure_all_scored_roads": (
            round(float(corridor_mean), 3) if corridor_mean is not None else None
        ),
        "enough_to_validate": len(exposures) >= 30,
        "note": (
            "Fewer than 30 matched reports: this is a sanity check, not a validation."
            if len(exposures) < 30
            else "Enough matches to begin testing the prior; fitting it is future work."
        ),
    }


@router.get("/status")
def model_status(db: Session = Depends(get_db)):
    history = load_history(db)
    latest_report = max(history.published) if history.published else None
    scored = db.execute(
        select(
            Road.current_accessibility_as_of,
            Road.accessibility_model_version,
            func.count(Road.id),
        )
        .where(Road.current_accessibility.isnot(None))
        .group_by(Road.current_accessibility_as_of, Road.accessibility_model_version)
    ).all()
    scoring_state = None
    if scored:
        as_of, version, n = scored[0]
        age = (date.today() - as_of).days
        scoring_state = {
            "as_of": as_of.isoformat(),
            "age_days": age,
            "stale": age > scoring.MAX_STALE_DAYS,
            "model_version": version,
            "roads_scored": int(n),
        }

    return {
        "artifacts": {str(h): _artifact_summary(dm.load(h)) for h in dm.HORIZONS},
        "data": {
            "published_report_days": len(history.published),
            "districts_seen": len(history.districts),
            "first_report": min(history.published).isoformat() if history.published else None,
            "latest_report": latest_report.isoformat() if latest_report else None,
        },
        "scoring": scoring_state,
        "live_track_record": _live_track_record(db, history),
        "exposure_prior": {
            "formula": (
                f"clamp(1 - height_above_district_floor / {scoring.EXPOSURE_RELIEF_M:g} m, "
                f"{scoring.EXPOSURE_FLOOR}, 1); floor = district "
                f"{int(scoring.FLOOR_PERCENTILE * 100)}th-percentile road elevation"
            ),
            "fitted": False,
            "check": _exposure_check(db),
        },
        "caveats": CAVEATS,
    }


@router.get("/districts")
def latest_district_forecasts(
    corridor_only: bool = Query(True),
    db: Session = Depends(get_db),
):
    latest = db.execute(select(func.max(DistrictFloodForecast.as_of_date))).scalar()
    if latest is None:
        return {"as_of": None, "districts": [], "note": "no forecasts stored yet"}

    stmt = select(DistrictFloodForecast).where(DistrictFloodForecast.as_of_date == latest)
    if corridor_only:
        stmt = stmt.where(DistrictFloodForecast.in_corridor.is_(True))
    rows = db.execute(
        stmt.order_by(DistrictFloodForecast.district_key, DistrictFloodForecast.horizon_days)
    ).scalars().all()

    # If a day was scored more than once (e.g. after a retrain), the most
    # recently created forecast wins per district and horizon. Comparing
    # version strings instead would be wrong: each horizon has its own
    # version, and "dfs-h3-..." sorts after "dfs-h1-...".
    newest: dict[tuple[str, int], DistrictFloodForecast] = {}
    for r in rows:
        key = (r.district_key, r.horizon_days)
        if key not in newest or r.created_at > newest[key].created_at:
            newest[key] = r

    grouped: dict[str, dict] = {}
    for r in sorted(newest.values(), key=lambda x: (x.district_key, x.horizon_days)):
        d = grouped.setdefault(
            r.district_key,
            {
                "district": r.display_name or r.district_key,
                "in_corridor": r.in_corridor,
                "affected_on_as_of": r.affected_on_as_of,
                "forecasts": [],
            },
        )
        d["forecasts"].append(
            {
                "horizon_days": r.horizon_days,
                "target_date": r.target_date.isoformat(),
                "probability": r.probability,
                "persistence_probability": r.persistence_probability,
                "model_kind": r.model_kind,
                "model_version": r.model_version,
            }
        )

    age = (date.today() - latest).days
    return {
        "as_of": latest.isoformat(),
        "age_days": age,
        "stale": age > scoring.MAX_STALE_DAYS,
        "districts": sorted(grouped.values(), key=lambda d: d["district"]),
        "caveat": CAVEATS["what_is_predicted"],
    }


@router.get("/explain/{district}")
def explain_district_forecast(
    district: str,
    as_of: date | None = Query(None, description="Report day; defaults to the latest."),
    db: Session = Depends(get_db),
):
    """Why the model gives a district its probability, feature by feature."""
    history = load_history(db)
    if not history.published:
        raise HTTPException(status_code=404, detail="no published reports ingested")
    as_of = as_of or max(history.published)
    key = district_key(district)
    if key is None or (key not in history.districts and normalise_district(district) is None):
        raise HTTPException(status_code=404, detail=f"unknown district {district!r}")
    features = features_for(history, key, as_of)
    if features is None:
        raise HTTPException(status_code=404, detail=f"no published report on {as_of}")

    explanations = []
    for h in dm.HORIZONS:
        payload = dm.load(h)
        if payload is not None:
            explanations.append(
                forecast_explain.explain(payload, features, history.display_names.get(key, key))
            )
    if not explanations:
        raise HTTPException(status_code=404, detail="no trained model")
    return {
        "district": history.display_names.get(key, key),
        "as_of": as_of.isoformat(),
        "explanations": explanations,
        "caveat": CAVEATS["what_is_predicted"],
    }
