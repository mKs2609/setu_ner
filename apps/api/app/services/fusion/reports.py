"""
Turning individual field reports into a per-road belief, and adjusting how
much each reporter's word is worth.

WHAT THIS IS AND IS NOT
This produces a **field-reported status**: what people on the ground are
currently saying about a road, with a confidence. It is deliberately kept
separate from `roads.current_accessibility`, which stays empty until there is
a real model (Phase 3). Writing a crowd consensus into the column reserved
for a model prediction would blur the observed/derived line this project has
held everywhere else -- and an operator reading "accessibility 0.2" cannot
tell whether that came from a trained model or from two people with phones.

When Model A exists, fusion becomes model prediction updated by these
reports. Until then the honest thing is to publish both side by side and let
the reader see which is which.

HOW THE BELIEF IS COMPUTED
Each recent report votes for its status, weighted by two things:

  trust     The reporter's score at the time they submitted. Frozen per
            report, so recomputing an old fusion gives the same answer.
  recency   A report decays over the window. A "blocked" from 20 hours ago
            is weaker evidence than one from 20 minutes ago, because roads
            get cleared.

The winning status is whichever has the most weight. Confidence is that
status's share of the total weight, so unanimity scores high and a genuine
split scores low -- which is the correct signal to an operator, not a
weakness to be smoothed over.

HOW TRUST MOVES
After a report lands, it is compared with the consensus of *other* recent
reports on the same road. Agreeing raises the reporter's score, contradicting
lowers it, and the update is damped by a prior so one disagreement cannot
swing someone from trusted to ignored.

    trust = 0.5 + 0.5 * (corroborated - contradicted)
                       / (corroborated + contradicted + PRIOR_WEIGHT)

Bounded well inside [0, 1] on both ends. Nobody reaches certainty and nobody
is silenced completely -- a reporter who has been wrong before may be the
first to see something real.

HONEST LIMITS
This is a heuristic, not a Bayesian model, and it is gameable: several
colluding reporters agreeing with each other will corroborate each other
upward. Mitigating that properly needs corroboration against independent
evidence -- satellite extent, the DRIMS damage rows -- rather than against
other reports, and that is Phase 3 work. The MVP is honest about being a
weighted vote.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import FieldReport, Reporter

# Reports older than this stop counting toward the current belief. A day is
# long enough to survive an overnight gap in reporting and short enough that
# yesterday's flood does not speak for today's road.
FUSION_WINDOW_HOURS = 24

# A report snapped further than this from any road is kept but excluded from
# fusion -- it is more likely a GPS error or a place we do not cover than a
# real observation about that road.
MAX_SNAP_DISTANCE_M = 250.0

# Damping on the trust update. Higher means slower to move.
PRIOR_WEIGHT = 4.0

TRUST_FLOOR = 0.05
TRUST_CEILING = 0.95
NEUTRAL_TRUST = 0.5

STATUSES = ("clear", "slow", "blocked")


@dataclass
class SnapResult:
    road_id: int | None
    distance_m: float | None
    within_range: bool


@dataclass
class FusedStatus:
    road_id: int
    status: str | None
    confidence: float
    report_count: int
    weight_by_status: dict[str, float]
    newest_report_at: datetime | None
    window_hours: int


def snap_to_road(db: Session, lon: float, lat: float) -> SnapResult:
    """Nearest road segment to a coordinate, with its true distance in metres.

    Ordering uses the PostGIS KNN operator so the spatial index does the work;
    the distance itself is computed on the geography type so it is real metres
    rather than degrees.
    """
    row = db.execute(
        text(
            """
            SELECT id,
                   ST_Distance(
                       geometry::geography,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                   ) AS distance_m
            FROM roads
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 1
            """
        ),
        {"lon": lon, "lat": lat},
    ).first()

    if row is None:
        return SnapResult(None, None, False)

    distance = float(row.distance_m)
    within = distance <= MAX_SNAP_DISTANCE_M
    return SnapResult(int(row.id) if within else None, distance, within)


def get_or_create_reporter(db: Session, reporter_id: str) -> Reporter:
    reporter = db.get(Reporter, reporter_id)
    now = datetime.now(timezone.utc)
    if reporter is None:
        reporter = Reporter(
            id=reporter_id,
            trust_score=NEUTRAL_TRUST,
            reports_submitted=0,
            times_corroborated=0,
            times_contradicted=0,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(reporter)
        # Flush here, not at commit. field_reports carries a foreign key to
        # this row, and the two tables are linked only by a ForeignKey column
        # with no ORM relationship -- so SQLAlchemy's unit of work has nothing
        # to order the inserts by, and the report insert would otherwise hit a
        # reporter row that does not exist yet.
        db.flush()
    reporter.last_seen_at = now
    return reporter


def recent_reports(db: Session, road_id: int, *, exclude_id: int | None = None):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FUSION_WINDOW_HOURS)
    stmt = select(FieldReport).where(
        FieldReport.road_id == road_id,
        FieldReport.submitted_at >= cutoff,
    )
    if exclude_id is not None:
        stmt = stmt.where(FieldReport.id != exclude_id)
    return db.execute(stmt.order_by(FieldReport.submitted_at.desc())).scalars().all()


def _recency_weight(submitted_at: datetime, now: datetime) -> float:
    """Linear decay across the window, floored so a report never counts zero
    while it is still inside the window."""
    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    age_h = max(0.0, (now - submitted_at).total_seconds() / 3600)
    return max(0.1, 1.0 - age_h / FUSION_WINDOW_HOURS)


def fuse(db: Session, road_id: int) -> FusedStatus:
    """What the ground is currently saying about one road."""
    reports = recent_reports(db, road_id)
    now = datetime.now(timezone.utc)

    weights = {s: 0.0 for s in STATUSES}
    for report in reports:
        if report.status not in weights:
            continue
        weights[report.status] += report.trust_at_submission * _recency_weight(
            report.submitted_at, now
        )

    total = sum(weights.values())
    if not reports or total <= 0:
        return FusedStatus(
            road_id=road_id,
            status=None,
            confidence=0.0,
            report_count=0,
            weight_by_status={k: round(v, 4) for k, v in weights.items()},
            newest_report_at=None,
            window_hours=FUSION_WINDOW_HOURS,
        )

    winner = max(weights, key=lambda s: weights[s])
    return FusedStatus(
        road_id=road_id,
        status=winner,
        confidence=round(weights[winner] / total, 3),
        report_count=len(reports),
        weight_by_status={k: round(v, 4) for k, v in weights.items()},
        newest_report_at=max(r.submitted_at for r in reports),
        window_hours=FUSION_WINDOW_HOURS,
    )


def _consensus_of(reports) -> str | None:
    """The plainly dominant status among a set of reports, or None when they
    do not agree. Used only to judge a new report, so a tie counts as no
    consensus rather than picking a side arbitrarily."""
    if not reports:
        return None
    counts: dict[str, float] = {}
    for report in reports:
        counts[report.status] = counts.get(report.status, 0.0) + report.trust_at_submission
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def update_trust(db: Session, reporter: Reporter, report: FieldReport) -> str:
    """Adjust the reporter's score against what others said about that road.

    Returns 'corroborated', 'contradicted' or 'no_consensus' so the API can
    tell the reporter what happened -- a trust score that moves invisibly is
    the kind of thing people rightly distrust.
    """
    if report.road_id is None:
        return "no_consensus"

    others = recent_reports(db, report.road_id, exclude_id=report.id)
    consensus = _consensus_of(others)

    if consensus is None:
        outcome = "no_consensus"
    elif consensus == report.status:
        reporter.times_corroborated += 1
        outcome = "corroborated"
    else:
        reporter.times_contradicted += 1
        outcome = "contradicted"

    agreed = reporter.times_corroborated
    disagreed = reporter.times_contradicted
    raw = NEUTRAL_TRUST + 0.5 * (agreed - disagreed) / (agreed + disagreed + PRIOR_WEIGHT)
    reporter.trust_score = round(min(TRUST_CEILING, max(TRUST_FLOOR, raw)), 4)
    return outcome


def reports_in_last_hour(db: Session, reporter_id: str) -> int:
    """Used for the submission rate limit. Not security -- an opaque id is
    trivially rotated -- but it stops one enthusiastic client or a retry loop
    from flooding a road with duplicates."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    return (
        db.execute(
            select(func.count(FieldReport.id)).where(
                FieldReport.reporter_id == reporter_id,
                FieldReport.submitted_at >= cutoff,
            )
        ).scalar_one()
        or 0
    )
