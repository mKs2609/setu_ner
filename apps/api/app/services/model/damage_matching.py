"""
Matching geolocated DRIMS damage reports to road segments.

    cd apps/api
    python -m app.services.model.damage_matching

`0004` stored the coordinates of damaged roads and bridges and left the join
to the road graph undone, because doing it honestly needs a threshold and a
way to say "no confident match". The thresholds:

  <= 100 m   confident     district coordinates are usually taken on site,
                           and the corridor's three in-graph points so far
                           sit 10-36 m from a mapped road
  <= 300 m   approximate   plausibly the same road, possibly a parallel one
  >  300 m   none          recorded with no road, never snapped

Most points are elsewhere in Assam, outside the road graph entirely. They
are recorded as 'none' too, which keeps the table an honest account of every
report rather than only the flattering ones.

Idempotent on observation id.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.db.session import SessionLocal

CONFIDENT_M = 100.0
APPROXIMATE_M = 300.0
MATCHED_METRICS = ("infrastructure_damage_point", "roads_damaged", "bridges_damaged")


def quality_for(distance_m: float | None) -> str:
    if distance_m is None:
        return "none"
    if distance_m <= CONFIDENT_M:
        return "confident"
    if distance_m <= APPROXIMATE_M:
        return "approximate"
    return "none"


# KNN on the planar operator finds a handful of candidates using the spatial
# index; true distance in metres is then measured on the geography. Planar
# degrees distort by ~10% at this latitude, which is why it only shortlists.
MATCH_SQL = text(
    """
    INSERT INTO road_damage_matches (observation_id, road_id, distance_m, quality, matched_at)
    SELECT o.id,
           CASE WHEN best.d <= :approx THEN best.road_id END,
           best.d,
           CASE WHEN best.d <= :confident THEN 'confident'
                WHEN best.d <= :approx THEN 'approximate'
                ELSE 'none' END,
           now()
    FROM hazard_observations o
    CROSS JOIN LATERAL (
        SELECT c.road_id, c.d FROM (
            SELECT r.id AS road_id,
                   ST_Distance(r.geometry::geography, o.geometry::geography) AS d
            FROM roads r
            ORDER BY r.geometry <-> o.geometry
            LIMIT 5
        ) c
        ORDER BY c.d
        LIMIT 1
    ) best
    WHERE o.geometry IS NOT NULL
      AND o.metric = ANY(:metrics)
      AND NOT EXISTS (SELECT 1 FROM road_damage_matches m WHERE m.observation_id = o.id)
    """
)


def match_all(db) -> int:
    result = db.execute(
        MATCH_SQL,
        {"confident": CONFIDENT_M, "approx": APPROXIMATE_M, "metrics": list(MATCHED_METRICS)},
    )
    db.commit()
    return result.rowcount or 0


def main() -> int:
    with SessionLocal() as db:
        written = match_all(db)
        counts = db.execute(
            text("SELECT quality, count(*) FROM road_damage_matches GROUP BY 1 ORDER BY 1")
        ).all()
    print(f"{written} new match record(s)")
    for quality, n in counts:
        print(f"  {quality:12} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
