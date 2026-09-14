"""
Saving recommendations and recording what operators did with them.

Records are written once and never updated. An operator who disagrees with a
plan does not edit it; they add an override saying what they did instead and
why. Both halves are needed later: the plan shows what the system knew, the
overrides show where that was not enough.

Rate limits are not security -- ids are opaque and trivially rotated, and
none of this is authenticated (same as field reports, 0005) -- but they stop
a retry loop or an enthusiastic client from filling the tables.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models import Recommendation, RecommendationOverride
from app.services.logistics import gazetteer
from app.services.model import district_model as dm

MAX_SAVES_PER_HOUR = 60
MAX_OVERRIDES_PER_OPERATOR_PER_HOUR = 30

ACTIONS = ("accepted", "modified", "rejected")
REASON_CATEGORIES = (
    "road_condition_differs",   # the route was not as the forecast said
    "stock_figure_wrong",       # the depot did not hold what was entered
    "fleet_unavailable",        # trucks or drivers not available
    "demand_differs",           # people on the ground differ from the report
    "priority_judgement",       # operator chose a different priority
    "other",
)


class RateLimited(Exception):
    pass


def model_versions() -> dict:
    versions = {}
    for h in dm.HORIZONS:
        a = dm.load(h)
        versions[f"district_flood_state_h{h}"] = a["version"] if a else None
    try:
        import json

        g = json.loads(gazetteer.GAZETTEER_PATH.read_text(encoding="utf-8"))
        versions["gazetteer_osm_timestamp"] = g.get("osm_data_timestamp")
    except (OSError, ValueError):
        versions["gazetteer_osm_timestamp"] = None
    return versions


def save(db, *, inputs: dict, plan: dict, explanation: dict, label: str | None) -> Recommendation:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.execute(
        select(func.count(Recommendation.id)).where(Recommendation.created_at >= cutoff)
    ).scalar_one()
    if recent >= MAX_SAVES_PER_HOUR:
        raise RateLimited(f"more than {MAX_SAVES_PER_HOUR} plans saved in the last hour")

    rec = Recommendation(
        id=uuid.uuid4().hex,
        kind="supply_plan",
        created_at=datetime.now(timezone.utc),
        data_as_of=date.fromisoformat(plan["as_of"]),
        is_replay=plan["is_replay"],
        example_inputs=plan["example_inputs"],
        model_versions=model_versions(),
        inputs=inputs,
        outputs=plan,
        explanation=explanation,
        label=label,
    )
    db.add(rec)
    db.commit()
    return rec


def add_override(
    db,
    rec: Recommendation,
    *,
    operator_id: str,
    action: str,
    reason_category: str,
    reason: str,
    target: str | None,
) -> RecommendationOverride:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.execute(
        select(func.count(RecommendationOverride.id)).where(
            RecommendationOverride.operator_id == operator_id,
            RecommendationOverride.created_at >= cutoff,
        )
    ).scalar_one()
    if recent >= MAX_OVERRIDES_PER_OPERATOR_PER_HOUR:
        raise RateLimited(
            f"more than {MAX_OVERRIDES_PER_OPERATOR_PER_HOUR} overrides in the last hour from this operator"
        )
    row = RecommendationOverride(
        recommendation_id=rec.id,
        created_at=datetime.now(timezone.utc),
        operator_id=operator_id,
        action=action,
        target=target,
        reason_category=reason_category,
        reason=reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def summary(rec: Recommendation, override_count: int | None = None) -> dict:
    plan = rec.outputs.get("plan", {})
    need = plan.get("person_days_needed_all_commodities") or 0
    covered = plan.get("person_days_covered_all_commodities") or 0
    return {
        "id": rec.id,
        "kind": rec.kind,
        "label": rec.label,
        "created_at": rec.created_at.isoformat(),
        "data_as_of": rec.data_as_of.isoformat(),
        "is_replay": rec.is_replay,
        "example_inputs": rec.example_inputs,
        "people_to_supply": rec.outputs.get("demand", {}).get("totals", {}).get("people_to_supply"),
        "coverage": round(covered / need, 4) if need else None,
        "worst_shortfall_fraction": plan.get("worst_shortfall_fraction"),
        "override_count": override_count,
    }


def override_dict(o: RecommendationOverride) -> dict:
    return {
        "id": o.id,
        "created_at": o.created_at.isoformat(),
        "operator_id": o.operator_id,
        "action": o.action,
        "target": o.target,
        "reason_category": o.reason_category,
        "reason": o.reason,
    }
