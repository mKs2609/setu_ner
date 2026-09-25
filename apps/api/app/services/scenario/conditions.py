"""
Turning what is currently reported into a starting state for routing.

WHY THIS EXISTS
The scenario engine has always routed on a clean graph. Every closure had to
be typed in by hand, which makes it a good tool for hypotheticals and a
useless one for "what is happening right now". Meanwhile the project ingests
a daily hazard bulletin and collects field reports, and neither has ever
touched a routing decision. This module is the join.

The project's own pitch is that existing systems tell you a flood is
happening while nothing tells you which road will still work when your truck
gets there. Answering that needs the live layers to reach the router, and
until now they did not.

WHAT IT IS NOT
This is not a prediction and not a model. Every road it marks is marked
because somebody reported it or a bulletin recorded damage near it. The
output is labelled "reported conditions" throughout, and each affected road
carries the reason it was included. A model prediction
becomes a fourth input here rather than a replacement for these.

A GRADUATED RESPONSE, NOT A SWITCH
Closing a road is a strong claim: it removes the road from the network and
can sever a corridor. One person saying "blocked" is real evidence and
should be visible, but it should not by itself delete a highway from the map.

So the response is graded by how much evidence there is:

  strong evidence of blocked    -> closed
  weaker evidence of blocked    -> heavily slowed, not removed
  reported slow                 -> slowed
  hazard damage reported nearby -> slowed

Independent corroboration (see services/fusion/corroboration.py) lowers the
bar for closing, because evidence nobody submitting reports controls is worth
more than another show of hands.

WHY DISTRICT DATA NEVER CLOSES A ROAD
The hazard bulletin is district-level. "Cachar reported four damaged roads"
does not identify which four out of fifty-one thousand. Letting that close
anything would be inventing specificity the source does not have. District
signals therefore only ever slow roads down, and only where a geolocated
damage point puts the damage near a particular road.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import FieldReport
from app.services.fusion import corroboration as corrob
from app.services.fusion import reports as fusion

# Weight needed before a reported blockage removes a road from the network.
# One fresh report from a neutral-trust reporter carries 0.5, so this asks for
# roughly two of them, or one from a well-established reporter.
CLOSE_WEIGHT = 1.0

# With independent corroboration the bar drops to a single credible report,
# because the supporting evidence is not something a reporter can manufacture.
CLOSE_WEIGHT_WITH_CORROBORATION = 0.45

# Applied to a road reported blocked without enough weight to close it. Large
# enough that the router avoids it unless there is no alternative, which is
# the right treatment for "somebody says this is impassable and we are not
# certain enough to delete it".
DEGRADE_FACTOR_WEAK_BLOCKED = 6.0
DEGRADE_FACTOR_SLOW = 2.5
DEGRADE_FACTOR_HAZARD_NEARBY = 1.8

# Degrees to expand a damage point by for the index-backed bounding-box
# screen. 2 km is about 0.020 degrees of longitude at this latitude and 0.018
# of latitude; 0.025 covers both with room to spare. It only has to be
# generous enough never to exclude a road the exact geography check would have
# accepted -- being too wide costs a little work, being too narrow silently
# loses evidence.
BBOX_DEGREES = 0.025

# How far back to look for field reports. Matches the fusion window: a report
# older than this no longer describes current conditions.
REPORT_WINDOW_HOURS = fusion.FUSION_WINDOW_HOURS


@dataclass
class AffectedRoad:
    road_id: int
    effect: str  # closed | degraded
    factor: float | None
    reason: str
    source: str
    confidence: float | None


@dataclass
class CurrentConditions:
    closed_road_ids: set[int] = field(default_factory=set)
    degraded: dict[int, float] = field(default_factory=dict)
    affected: list[AffectedRoad] = field(default_factory=list)
    roads_with_reports: int = 0
    report_window_hours: int = REPORT_WINDOW_HOURS

    def as_dict(self) -> dict:
        return {
            "closed_count": len(self.closed_road_ids),
            "degraded_count": len(self.degraded),
            "roads_with_recent_reports": self.roads_with_reports,
            "report_window_hours": self.report_window_hours,
            "affected_roads": [
                {
                    "road_id": a.road_id,
                    "effect": a.effect,
                    "travel_time_multiplier": a.factor,
                    "reason": a.reason,
                    "source": a.source,
                    "confidence": a.confidence,
                }
                for a in self.affected
            ],
            "caveats": {
                "not_a_prediction": (
                    "These are reported conditions, not a forecast. Every road "
                    "listed is here because somebody reported it or a bulletin "
                    "recorded damage near it. No model is involved."
                ),
                "coverage": (
                    "Only roads with recent reports can appear. The corridor has "
                    "110,266 segments, so silence about a road means nobody has "
                    "reported it -- not that it is known to be open."
                ),
                "district_data_never_closes": (
                    "District-level hazard counts do not identify individual "
                    "roads, so they only ever slow a road down, and only where a "
                    "geolocated damage point puts the damage nearby."
                ),
            },
        }


def _roads_with_recent_reports(db: Session) -> list[int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=REPORT_WINDOW_HOURS)
    rows = db.execute(
        select(FieldReport.road_id)
        .where(FieldReport.road_id.isnot(None), FieldReport.submitted_at >= cutoff)
        .distinct()
    ).scalars().all()
    return [int(r) for r in rows]


def _hazard_degraded_roads(db: Session) -> list[tuple[int, str, datetime | None]]:
    """Roads near a geolocated damage point from the hazard bulletin.

    Deliberately point-based. A district count cannot name a road, so it never
    reaches here; only a damage point with coordinates can put a specific
    stretch of road under suspicion.

    The bounding-box test comes first and does the real work. Casting to
    geography for an exact distance is correct but unindexable, so filtering
    on it alone made Postgres scan all 110,266 roads -- 34 seconds a call.
    Screening with the `&&` operator against an expanded box uses the GiST
    index on roads.geometry, and the geography check then refines the handful
    that survive. Same answers, ~0.02s.
    """
    rows = db.execute(
        text(
            """
            WITH pts AS (
                SELECT id, geometry, place_name, observed_at
                FROM hazard_observations
                WHERE geometry IS NOT NULL
                  AND observed_at >= :cutoff
            )
            SELECT DISTINCT ON (r.id)
                   r.id AS road_id,
                   p.place_name,
                   p.observed_at
            FROM pts p
            JOIN roads r
              ON r.geometry && ST_Expand(p.geometry, :bbox_degrees)
             AND ST_DWithin(r.geometry::geography, p.geometry::geography, :radius)
            ORDER BY r.id, p.observed_at DESC
            LIMIT 5000
            """
        ),
        {
            "radius": corrob.DAMAGE_POINT_RADIUS_M,
            "bbox_degrees": BBOX_DEGREES,
            "cutoff": datetime.now(timezone.utc)
            - timedelta(hours=corrob.WINDOW_DAMAGE_POINT_HOURS),
        },
    ).mappings()
    return [(int(r["road_id"]), r["place_name"] or "unnamed", r["observed_at"]) for r in rows]


def derive(db: Session) -> CurrentConditions:
    """Read the live layers and produce a starting state for the router."""
    conditions = CurrentConditions()

    road_ids = _roads_with_recent_reports(db)
    conditions.roads_with_reports = len(road_ids)

    for road_id in road_ids:
        fused = fusion.fuse(db, road_id)
        if not fused.status or fused.status == "clear":
            continue

        weight = fused.weight_by_status.get(fused.status, 0.0)

        if fused.status == "blocked":
            evidence = corrob.corroborate(
                db,
                road_id=road_id,
                district=_district_of(db, road_id),
                status="blocked",
            )
            threshold = (
                CLOSE_WEIGHT_WITH_CORROBORATION if evidence.supports else CLOSE_WEIGHT
            )
            if weight >= threshold:
                conditions.closed_road_ids.add(road_id)
                conditions.affected.append(
                    AffectedRoad(
                        road_id=road_id,
                        effect="closed",
                        factor=None,
                        reason=(
                            f"Reported blocked by {fused.report_count} report"
                            f"{'' if fused.report_count == 1 else 's'} "
                            f"(evidence weight {weight:.2f} >= {threshold})"
                            + (
                                ", with independent hazard data supporting it"
                                if evidence.supports
                                else ""
                            )
                        ),
                        source="field_reports"
                        + ("+hazard_data" if evidence.supports else ""),
                        confidence=fused.confidence,
                    )
                )
            else:
                conditions.degraded[road_id] = DEGRADE_FACTOR_WEAK_BLOCKED
                conditions.affected.append(
                    AffectedRoad(
                        road_id=road_id,
                        effect="degraded",
                        factor=DEGRADE_FACTOR_WEAK_BLOCKED,
                        reason=(
                            f"Reported blocked, but evidence weight {weight:.2f} is "
                            f"below the {threshold} needed to remove a road from "
                            f"the network. Heavily slowed instead."
                        ),
                        source="field_reports",
                        confidence=fused.confidence,
                    )
                )

        elif fused.status == "slow":
            conditions.degraded[road_id] = DEGRADE_FACTOR_SLOW
            conditions.affected.append(
                AffectedRoad(
                    road_id=road_id,
                    effect="degraded",
                    factor=DEGRADE_FACTOR_SLOW,
                    reason=(
                        f"Reported slow by {fused.report_count} report"
                        f"{'' if fused.report_count == 1 else 's'}"
                    ),
                    source="field_reports",
                    confidence=fused.confidence,
                )
            )

    # Hazard damage points slow roads they sit near, unless a field report has
    # already said something stronger about that road.
    for road_id, place, observed_at in _hazard_degraded_roads(db):
        if road_id in conditions.closed_road_ids or road_id in conditions.degraded:
            continue
        conditions.degraded[road_id] = DEGRADE_FACTOR_HAZARD_NEARBY
        conditions.affected.append(
            AffectedRoad(
                road_id=road_id,
                effect="degraded",
                factor=DEGRADE_FACTOR_HAZARD_NEARBY,
                reason=(
                    f"Infrastructure damage reported nearby in {place}"
                    + (f" on {observed_at.date().isoformat()}" if observed_at else "")
                ),
                source="hazard_data",
                confidence=None,
            )
        )

    return conditions


def _district_of(db: Session, road_id: int) -> str | None:
    from app.db.models import Road

    road = db.get(Road, road_id)
    return road.district if road else None
