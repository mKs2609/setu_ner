"""
Scoring: turning district forecasts into per-road accessibility.

    cd apps/api
    python -m app.services.model.score                 # latest report
    python -m app.services.model.score --as-of 2026-09-01 --allow-stale

HOW A ROAD GETS ITS NUMBER

    current_accessibility = 1 - P(district affected tomorrow) x terrain exposure

Two parts, and they deserve very different amounts of trust:

  P(district affected)  From the evaluated district model. Its test-season
                        numbers, and whether it beats persistence, are in the
                        artifact and on /api/v1/model/status.

  terrain exposure      A PRIOR, NOT A FITTED MODEL. How far a road sits above
                        its own district's low ground:

                            exposure = clamp(1 - height_above_floor / 100 m, 0.1, 1)

                        where the floor is the district's 10th-percentile
                        road elevation. Valley roads get 1.0; a road 100 m or
                        more above the floor gets 0.1, never zero. The 100 m
                        and the 0.1 are judgement, stated here rather than
                        buried. Fitting them needs geolocated road damage in
                        volume, and the corridor has single digits.

So the per-road spread is physics plus a stated assumption, while the
district level is a measured prediction. The API returns both parts
separately so nobody has to take the product on faith, and confidence is
recorded as 'low' for exactly this reason.

WHAT IS NEVER WRITTEN
  - A stale forecast. If the newest report is more than MAX_STALE_DAYS old,
    scoring refuses unless told otherwise: a "current" accessibility computed
    from last week's report is wrong in the way that matters most.
  - A value without its model version and as-of date.
  - Anything for roads outside Assam's reporting (the Meghalaya districts):
    no forecast exists for them, so they stay NULL rather than borrowing a
    neighbour's.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db.models import DistrictFloodForecast
from app.db.session import SessionLocal
from app.services.ingestion.districts import CORRIDOR_DISTRICTS
from app.services.model import district_model as dm
from app.services.model import shadow
from app.services.model.dataset import ReportHistory, features_for
from app.services.model.history import load_history

MAX_STALE_DAYS = 3
EXPOSURE_RELIEF_M = 100.0
EXPOSURE_FLOOR = 0.1
FLOOR_PERCENTILE = 0.10
CONFIDENCE = "low"


def exposure(height_above_floor_m: float | None) -> float | None:
    """The terrain prior, as a plain function so it can be tested directly.
    The SQL below implements the same formula."""
    if height_above_floor_m is None:
        return None
    return max(EXPOSURE_FLOOR, min(1.0, 1.0 - height_above_floor_m / EXPOSURE_RELIEF_M))


def accessibility(probability: float, road_exposure: float) -> float:
    return round(1.0 - probability * road_exposure, 4)


def forecast_districts(
    history: ReportHistory, as_of: date, artifacts: dict[int, dict]
) -> list[dict]:
    """Forecast every district in the history, plus every corridor district
    even if it has never been listed (a never-flooded district still needs a
    forecast, and its features correctly say 'not affected')."""
    keys = sorted(set(history.districts) | CORRIDOR_DISTRICTS)
    out = []
    for key in keys:
        feats = features_for(history, key, as_of)
        if feats is None:
            raise ValueError(f"no published report on {as_of}; cannot forecast from it")
        for h, artifact in artifacts.items():
            payload = dm.for_inputs(artifact, feats)
            persistence = dm.Predictor("persistence", payload["baselines"]["persistence"])
            a = np.asarray([int(feats["affected"])])
            X = np.zeros((1, len(payload["features"])))
            out.append(
                {
                    "district_key": key,
                    "display_name": history.display_names.get(key, key),
                    "in_corridor": key in CORRIDOR_DISTRICTS,
                    "horizon_days": h,
                    "probability": round(dm.predict_one(payload, feats), 5),
                    "persistence_probability": round(float(persistence.predict(X, a)[0]), 5),
                    "affected_on_as_of": bool(feats["affected"]),
                    "model_version": payload["version"],
                    # "persistence_fallback" marks a row the model could not
                    # score (see district_model.for_inputs), so the track
                    # record can tell the model's misses from the fallback's.
                    "model_kind": (
                        "persistence_fallback" if "fallback_reason" in payload
                        else payload["kind"]
                    ),
                }
            )
    return out


def store_forecasts(db, as_of: date, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc)
    values = [
        {**r, "as_of_date": as_of, "target_date": as_of + timedelta(days=r["horizon_days"]),
         "created_at": now}
        for r in rows
    ]
    if not values:
        return 0
    stmt = insert(DistrictFloodForecast).values(values).on_conflict_do_nothing(
        constraint="uq_forecast_identity"
    )
    result = db.execute(stmt)
    return result.rowcount or 0


UPDATE_ROADS_SQL = text(
    """
    WITH floor AS (
        SELECT district,
               percentile_cont(:pct) WITHIN GROUP (ORDER BY elevation_m) AS floor_m
        FROM roads
        WHERE elevation_m IS NOT NULL AND district IS NOT NULL
        GROUP BY district
    ),
    forecast AS (
        SELECT * FROM json_to_recordset(CAST(:forecasts AS json))
            AS f(district text, p1 double precision, p3 double precision)
    ),
    scored AS (
        SELECT r.id,
               GREATEST(:exp_floor, LEAST(1.0, 1.0 - (r.elevation_m - fl.floor_m) / :relief)) AS exposure,
               fc.p1, fc.p3
        FROM roads r
        JOIN floor fl ON fl.district = r.district
        JOIN forecast fc ON fc.district = r.district
        WHERE r.elevation_m IS NOT NULL
    )
    UPDATE roads r
    SET hazard_exposure = round(s.exposure::numeric, 4),
        current_accessibility = round((1 - s.p1 * s.exposure)::numeric, 4),
        predicted_accessibility = json_build_object(
            'h1', json_build_object('target_date', :target1,
                                    'accessibility', round((1 - s.p1 * s.exposure)::numeric, 4)),
            'h3', json_build_object('target_date', :target3,
                                    'accessibility', round((1 - s.p3 * s.exposure)::numeric, 4))
        )::text,
        confidence = :confidence,
        accessibility_model_version = :version,
        current_accessibility_as_of = :as_of
    FROM scored s
    WHERE r.id = s.id
    """
)

# Roads a previous run scored but this one cannot (no elevation, or a
# district with no forecast) are cleared, so an old value never sits next to
# new ones looking current.
CLEAR_UNSCORED_SQL = text(
    """
    UPDATE roads
    SET current_accessibility = NULL, predicted_accessibility = NULL,
        hazard_exposure = NULL, confidence = NULL,
        accessibility_model_version = NULL, current_accessibility_as_of = NULL
    WHERE accessibility_model_version IS NOT NULL
      AND (current_accessibility_as_of IS DISTINCT FROM :as_of
           OR accessibility_model_version IS DISTINCT FROM :version)
    """
)


def score_roads(db, as_of: date, forecasts: list[dict], version: str) -> int:
    by_district: dict[str, dict] = {}
    for f in forecasts:
        if f["in_corridor"]:
            by_district.setdefault(f["district_key"], {})[f["horizon_days"]] = f["probability"]
    payload = [
        {"district": d, "p1": hs[1], "p3": hs[3]}
        for d, hs in by_district.items()
        if 1 in hs and 3 in hs
    ]
    result = db.execute(
        UPDATE_ROADS_SQL,
        {
            "pct": FLOOR_PERCENTILE,
            "forecasts": json.dumps(payload),
            "exp_floor": EXPOSURE_FLOOR,
            "relief": EXPOSURE_RELIEF_M,
            "target1": (as_of + timedelta(days=1)).isoformat(),
            "target3": (as_of + timedelta(days=3)).isoformat(),
            "confidence": CONFIDENCE,
            "version": version,
            "as_of": as_of,
        },
    )
    written = result.rowcount or 0
    db.execute(CLEAR_UNSCORED_SQL, {"as_of": as_of, "version": version})
    return written


def run(as_of: date | None = None, allow_stale: bool = False, today: date | None = None) -> dict:
    today = today or date.today()
    artifacts = {h: dm.load(h) for h in dm.HORIZONS}
    missing = [h for h, a in artifacts.items() if a is None]
    if missing:
        return {"status": "no_model", "detail": f"no trained artifact for horizon(s) {missing}"}

    with SessionLocal() as db:
        history = load_history(db)
        if not history.published:
            return {"status": "no_data", "detail": "no published reports ingested"}
        as_of = as_of or max(history.published)
        age = (today - as_of).days
        if age > MAX_STALE_DAYS and not allow_stale:
            return {
                "status": "stale",
                "detail": (
                    f"newest usable report is {as_of} ({age} days old); refusing to "
                    f"publish it as current accessibility. Run ingestion first, or "
                    f"pass --allow-stale for a historical scoring."
                ),
            }

        forecasts = forecast_districts(history, as_of, artifacts)
        stored = store_forecasts(db, as_of, forecasts)
        # One version string identifies the pair of horizon artifacts.
        version = "+".join(artifacts[h]["version"] for h in dm.HORIZONS)
        roads = score_roads(db, as_of, forecasts, version)

        # The shadow test (services/model/shadow.py). Stored beside the served
        # forecasts for grading; never used for roads, maps or explanations.
        challengers = {
            h: c for h in dm.HORIZONS if (c := shadow.load_challenger(h)) is not None
        }
        shadow_stored = shadow_skipped = 0
        if challengers:
            raw = forecast_districts(history, as_of, challengers)
            rows = shadow.shadow_rows(raw)
            shadow_skipped = len(raw) - len(rows)
            shadow_stored = store_forecasts(db, as_of, rows)
        db.commit()

    corridor = {
        f["district_key"]: f["probability"]
        for f in forecasts
        if f["in_corridor"] and f["horizon_days"] == 1
    }
    return {
        "status": "success",
        "as_of": as_of.isoformat(),
        "age_days": age,
        "forecasts_stored": stored,
        "roads_scored": roads,
        "shadow_forecasts_stored": shadow_stored,
        # Rows the challenger could not score (rain not yet published); not
        # stored, so they neither help nor hurt it.
        "shadow_skipped_missing_inputs": shadow_skipped,
        "corridor_p_affected_tomorrow": corridor,
        "model_version": version,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score roads from the latest report.")
    parser.add_argument("--as-of", help="YYYY-MM-DD report day to score from.")
    parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args(argv)

    result = run(
        as_of=date.fromisoformat(args.as_of) if args.as_of else None,
        allow_stale=args.allow_stale,
    )
    for k, v in result.items():
        print(f"{k}: {v}")
    # Stale and no-model are refusals a scheduler should notice.
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
