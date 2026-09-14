"""
Why a road has the accessibility it has.

The number is 1 - P(district affected tomorrow) x terrain exposure (0010), so
the explanation has exactly two halves and says how much trust each deserves:
the district probability is a measured forecast, explained feature by feature
by forecast.py; the exposure is a stated prior, explained by the road's
height above its district's low ground.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.models import Road
from app.services.ingestion.districts import CORRIDOR_DISTRICTS
from app.services.explain import forecast as forecast_explain
from app.services.model import district_model as dm
from app.services.model import score as scoring
from app.services.model.dataset import features_for
from app.services.model.history import load_history

FLOOR_SQL = text(
    """
    SELECT percentile_cont(:pct) WITHIN GROUP (ORDER BY elevation_m)
    FROM roads WHERE district = :district AND elevation_m IS NOT NULL
    """
)


def explain(db, road: Road) -> dict:
    if road.current_accessibility is None:
        return {
            "road_id": road.id,
            "scored": False,
            "headline": (
                "This road has no forecast: "
                + (
                    "it is in a district outside Assam's daily reporting."
                    if road.district not in CORRIDOR_DISTRICTS
                    else "it has no elevation sample, so the terrain prior cannot be computed."
                )
            ),
        }

    as_of = road.current_accessibility_as_of
    artifact = dm.load(1)
    history = load_history(db)
    features = features_for(history, road.district, as_of) if artifact else None
    district_part = (
        forecast_explain.explain(artifact, features, road.district)
        if artifact and features is not None
        else None
    )
    p = district_part["probability"] if district_part else None
    # The stored value was computed by whichever model was current at scoring
    # time. If the artifact has since been retrained, this explanation would
    # describe a different model than the number it explains -- say so.
    same_model = bool(
        artifact and road.accessibility_model_version
        and artifact["version"] in road.accessibility_model_version.split("+")
    )

    floor = db.execute(
        FLOOR_SQL, {"pct": scoring.FLOOR_PERCENTILE, "district": road.district}
    ).scalar()
    height = None if (floor is None or road.elevation_m is None) else road.elevation_m - floor
    exposure = road.hazard_exposure

    if height is None:
        exposure_sentence = "Its terrain exposure could not be recomputed."
    elif height <= 0:
        exposure_sentence = (
            f"It sits at {road.elevation_m:.0f} m, at or below {road.district}'s low ground "
            f"({floor:.0f} m), so it takes the full district risk (exposure 1.0)."
        )
    elif exposure is not None and exposure <= scoring.EXPOSURE_FLOOR + 1e-9:
        exposure_sentence = (
            f"It sits {height:.0f} m above {road.district}'s low ground, beyond "
            f"{scoring.EXPOSURE_RELIEF_M:.0f} m, so it takes only the minimum "
            f"{scoring.EXPOSURE_FLOOR:.0%} of the district risk — never zero."
        )
    else:
        exposure_sentence = (
            f"It sits {height:.0f} m above {road.district}'s low ground, so it takes "
            f"{exposure:.0%} of the district risk."
        )

    headline = (
        f"Accessibility {road.current_accessibility:.3f} = 1 − {p:.3f} (chance {road.district} "
        f"is flood-affected tomorrow) × {exposure:.2f} (this road's terrain exposure). "
        + exposure_sentence
        if p is not None and exposure is not None
        else f"Accessibility {road.current_accessibility:.2f}. " + exposure_sentence
    )

    baseline = road.baseline_accessibility
    comparison = None
    if baseline is not None:
        diff = road.current_accessibility - baseline
        comparison = (
            f"The 2025 historical baseline for this road is {baseline:.2f}; the forecast is "
            f"{abs(diff):.2f} {'higher' if diff > 0 else 'lower' if diff < 0 else 'the same'}. "
            "The baseline describes the whole 2025 season; the forecast describes tomorrow."
        )

    return {
        "road_id": road.id,
        "scored": True,
        "as_of": as_of.isoformat() if as_of else None,
        "headline": headline,
        "district_forecast": district_part,
        "terrain": {
            "elevation_m": road.elevation_m,
            "district_floor_m": None if floor is None else round(floor, 1),
            "height_above_floor_m": None if height is None else round(height, 1),
            "exposure": exposure,
            "is_a_prior": True,
            "formula": (
                f"clamp(1 − height / {scoring.EXPOSURE_RELIEF_M:.0f} m, "
                f"{scoring.EXPOSURE_FLOOR}, 1)"
            ),
        },
        "baseline_comparison": comparison,
        "explains_stored_value": same_model,
        "model_mismatch_note": None if same_model else (
            "The model was retrained after this road was scored, so the district explanation "
            "describes the current model, not the one that produced the stored value. "
            "Re-run scoring to bring them back in line."
        ),
        "trust": (
            "The district probability is an evaluated forecast. The terrain exposure is a "
            "stated assumption that has not been fitted to observed road damage."
        ),
    }
