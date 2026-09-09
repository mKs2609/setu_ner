"""
Checking field reports against independent evidence.

THE PROBLEM THIS FIXES
`0005` shipped a trust model that judges a report against *other recent
reports on the same road*. That is circular: several people agreeing with
each other raise each other's scores, so a small colluding group can
manufacture trust from nothing. The limitation was documented, and the fix
named -- corroborate against evidence nobody submitting reports controls.

`0004` produced exactly that. The DRIMS daily reports carry per-district
road, bridge and embankment damage, plus geolocated damage points, published
by district administrations. A group gaming the report form has no way to
put a damage row in a government bulletin.

THE ASYMMETRY, WHICH IS THE WHOLE DESIGN
Independent evidence may **corroborate a report. It may never contradict
one.** That is not caution for its own sake; it follows from what the source
actually is:

  It lags.        DRIMS is compiled daily from what districts submit. In the
                  2022 Bethukandi dyke breach an on-site engineer reported it
                  by radio before it appeared in any feed. A rule that
                  penalised him for being ahead of the bulletin would punish
                  precisely the reports worth the most.

  It is coarse.   District-level counts say nothing about one road. "Cachar
                  reported zero damaged roads" is not a statement that a
                  particular road is fine.

  It is narrow.   A road can be impassable without any "damaged
                  infrastructure" to report -- a fallen tree, standing water,
                  landslide debris across the carriageway.

So absence of evidence here is genuinely not evidence of absence, and the
code treats it that way: no evidence found leaves trust exactly where peer
consensus put it.

WHAT CORROBORATION DOES CHANGE
Two things, both aimed squarely at the collusion hole:

  1. A report with independent backing counts as corroborated even when
     nobody else has reported that road. An honest lone reporter no longer
     needs company to build trust.

  2. A report with independent backing cannot be *penalised* by peers
     disagreeing. A contradiction is downgraded to "no consensus" instead.
     This is the part that breaks collusion: a group can outvote a lone
     honest reporter, but they cannot outvote a government damage bulletin.

CLEAR REPORTS ARE NEUTRAL, NOT CONTRADICTED
Damage evidence supports "blocked" and "slow". For "clear" it is deliberately
neutral -- a specific road can be perfectly passable in a district that is
flooding elsewhere, and scoring that as a contradiction would punish accurate
good news.

THE WEIGHTS ARE A JUDGEMENT CALL
The numbers below are not derived from anything. They are ordered by how
directly each kind of evidence bears on one road, and calibrated so that a
district merely being flood-affected is NOT on its own enough to corroborate
a specific road, while reported infrastructure damage in that district is.
They are flagged as assumptions in the API response for the same reason the
0.7 bridge factor is flagged in the baseline score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

# HOW LONG EACH KIND OF EVIDENCE STAYS RELEVANT
# A flat window would be the easy choice and the wrong one: these three things
# decay at completely different rates.
#
#   A district's flood-affected flag is a statement about today. It is stale
#   within a day or two.
#
#   Reported infrastructure damage is a statement about repair work. Roads and
#   bridges are not fixed in three days, least of all mid-monsoon.
#
#   A geolocated damage point is the most durable of the three: it names a
#   specific piece of broken infrastructure, and it stays broken until somebody
#   mends it.
#
# All three are still judgement calls, not measurements.
WINDOW_IMPACT_HOURS = 72
WINDOW_INFRASTRUCTURE_HOURS = 7 * 24
WINDOW_DAMAGE_POINT_HOURS = 14 * 24

# The widest of them, used where a single number has to stand for "the
# lookback" -- for instance when comparing against the peer-fusion window.
EVIDENCE_WINDOW_HOURS = WINDOW_DAMAGE_POINT_HOURS

# A geolocated damage point this close to the reported road is treated as
# bearing on it. Generous on purpose: the coordinates are supplied by district
# offices, not surveyed, and the report itself snapped to a road within 250 m.
DAMAGE_POINT_RADIUS_M = 2000.0

# Contribution of each kind of evidence. Assumptions, not measurements.
WEIGHT_DAMAGE_POINT = 0.6
WEIGHT_DISTRICT_INFRASTRUCTURE = 0.3
WEIGHT_DISTRICT_IMPACT = 0.15

# A district merely being flood-affected (0.15) falls below this on its own;
# reported infrastructure damage (0.3) meets it. That boundary is the point of
# the calibration.
SUPPORT_THRESHOLD = 0.3

INFRASTRUCTURE_METRICS = ("roads_damaged", "bridges_damaged", "embankments_breached")
IMPACT_METRICS = (
    "district_reported_affected",
    "villages_affected",
    "population_affected",
)

# Statuses that damage evidence can speak to at all.
IMPASSABILITY_STATUSES = ("blocked", "slow")


@dataclass
class Evidence:
    kind: str
    strength: float
    detail: str
    observed_at: datetime | None
    source: str


@dataclass
class Corroboration:
    score: float
    supports: bool
    evidence: list[Evidence] = field(default_factory=list)
    window_hours: int = EVIDENCE_WINDOW_HOURS
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "supports": self.supports,
            "window_hours": self.window_hours,
            "evidence": [
                {
                    "kind": e.kind,
                    "strength": e.strength,
                    "detail": e.detail,
                    "observed_at": e.observed_at,
                    "source": e.source,
                }
                for e in self.evidence
            ],
            "note": self.note,
            "caveat": (
                "Independent evidence can support a report but never counts "
                "against one. DRIMS is daily, district-level and lags what is "
                "happening on a road, so finding nothing here means nothing "
                "was found -- not that the reporter is wrong."
            ),
        }


def _cutoff(window_hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=window_hours)


def _damage_points_near_road(
    db: Session, road_id: int, window_hours: int
) -> list[dict]:
    """Geolocated damage points within range of the reported road.

    Distance is measured road-geometry to point on the geography type, so it
    is real metres against the whole line rather than to one endpoint.
    """
    rows = db.execute(
        text(
            """
            SELECT h.id,
                   h.observed_at,
                   h.value_text,
                   h.place_name,
                   h.source,
                   ST_Distance(r.geometry::geography, h.geometry::geography) AS distance_m
            FROM hazard_observations h
            JOIN roads r ON r.id = :road_id
            WHERE h.geometry IS NOT NULL
              AND h.observed_at >= :cutoff
              AND ST_DWithin(r.geometry::geography, h.geometry::geography, :radius)
            ORDER BY distance_m
            LIMIT 5
            """
        ),
        {
            "road_id": road_id,
            "cutoff": _cutoff(window_hours),
            "radius": DAMAGE_POINT_RADIUS_M,
        },
    ).mappings()
    return [dict(r) for r in rows]


def _district_signals(
    db: Session, district: str, metrics: tuple[str, ...], window_hours: int
) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT metric, value_num, unit, observed_at, source
            FROM hazard_observations
            WHERE district = :district
              AND metric = ANY(:metrics)
              AND value_num > 0
              AND observed_at >= :cutoff
            ORDER BY observed_at DESC
            """
        ),
        {
            "district": district,
            "metrics": list(metrics),
            "cutoff": _cutoff(window_hours),
        },
    ).mappings()
    return [dict(r) for r in rows]


def corroborate(
    db: Session,
    *,
    road_id: int | None,
    district: str | None,
    status: str,
    window_hours: int | None = None,
) -> Corroboration:
    """Look for independent evidence bearing on one report.

    By default each kind of evidence uses its own lookback (see the window
    constants above), because they go stale at very different rates. Passing
    `window_hours` overrides all of them with one value -- useful for asking
    "what does the last hour alone say?", and for tests.
    """
    w_point = window_hours if window_hours is not None else WINDOW_DAMAGE_POINT_HOURS
    w_infra = window_hours if window_hours is not None else WINDOW_INFRASTRUCTURE_HOURS
    w_impact = window_hours if window_hours is not None else WINDOW_IMPACT_HOURS
    reported_window = window_hours if window_hours is not None else EVIDENCE_WINDOW_HOURS
    if status not in IMPASSABILITY_STATUSES:
        return Corroboration(
            score=0.0,
            supports=False,
            window_hours=reported_window,
            note=(
                f"Damage evidence is treated as neutral for a '{status}' report. "
                f"A road can be perfectly passable in a district that is "
                f"flooding elsewhere, so good news is not scored against."
            ),
        )

    if road_id is None:
        return Corroboration(
            score=0.0,
            supports=False,
            window_hours=reported_window,
            note=(
                "This report snapped to no road in the corridor, so there is "
                "nothing to match independent evidence against."
            ),
        )

    found: list[Evidence] = []

    for point in _damage_points_near_road(db, road_id, w_point):
        found.append(
            Evidence(
                kind="damage_point_nearby",
                strength=WEIGHT_DAMAGE_POINT,
                detail=(
                    f"Infrastructure damage reported "
                    f"{point['distance_m'] / 1000:.1f} km away"
                    + (f" ({point['place_name']})" if point.get("place_name") else "")
                ),
                observed_at=point["observed_at"],
                source=point["source"],
            )
        )
        break  # the nearest one is enough; more does not make it more true

    if district:
        infra = _district_signals(db, district, INFRASTRUCTURE_METRICS, w_infra)
        if infra:
            top = infra[0]
            found.append(
                Evidence(
                    kind="district_infrastructure_damage",
                    strength=WEIGHT_DISTRICT_INFRASTRUCTURE,
                    detail=(
                        f"{district} reported {top['metric'].replace('_', ' ')}: "
                        f"{top['value_num']:.0f}"
                    ),
                    observed_at=top["observed_at"],
                    source=top["source"],
                )
            )

        impact = _district_signals(db, district, IMPACT_METRICS, w_impact)
        if impact:
            top = impact[0]
            found.append(
                Evidence(
                    kind="district_flood_impact",
                    strength=WEIGHT_DISTRICT_IMPACT,
                    detail=(
                        f"{district} reported {top['metric'].replace('_', ' ')}: "
                        f"{top['value_num']:.0f}"
                    ),
                    observed_at=top["observed_at"],
                    source=top["source"],
                )
            )

    score = min(1.0, sum(e.strength for e in found))
    supports = score >= SUPPORT_THRESHOLD

    if not found:
        note = (
            "No independent evidence found in the last "
            f"{reported_window} h. That does not count against the "
            "report -- the bulletin is daily, district-level, and routinely "
            "behind what someone standing on the road can see."
        )
    elif supports:
        note = "Independent evidence supports this report."
    else:
        note = (
            "Some related evidence exists, but district-level flood impact "
            "alone is not specific enough to corroborate one road."
        )

    return Corroboration(
        score=score,
        supports=supports,
        evidence=found,
        window_hours=reported_window,
        note=note,
    )
