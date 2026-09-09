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


@dataclass
class TrustUpdate:
    """What happened to a reporter's score, and on what grounds."""

    outcome: str  # corroborated | contradicted | no_consensus
    basis: str  # peers | independent_evidence | both | none
    peer_consensus: str | None
    independently_supported: bool
    trust_score: float
    explanation: str


def decide_outcome(
    peer_consensus: str | None,
    report_status: str,
    independently_supported: bool,
) -> tuple[str, str, str]:
    """The trust rule, as a pure function of the three inputs.

    Separated out so it can be tested exhaustively without a database -- this
    is where the judgement lives, and it is what a reviewer will push on.

    The rule that matters is the last branch: independent evidence outranks
    peer disagreement. A colluding group can outvote a lone honest reporter,
    but they cannot outvote a government damage bulletin, and that is the
    whole reason this function exists (see corroboration.py).
    """
    peers_agree = peer_consensus is not None and peer_consensus == report_status
    peers_disagree = peer_consensus is not None and peer_consensus != report_status

    if peers_agree and independently_supported:
        return (
            "corroborated",
            "both",
            "Other recent reports agree with you, and independent hazard data supports it.",
        )
    if peers_agree:
        return (
            "corroborated",
            "peers",
            "Other recent reports on that road agree with you.",
        )
    if independently_supported:
        # Covers both "nobody else reported" and "others disagreed". Evidence
        # nobody submitting reports controls carries more weight than a show
        # of hands.
        detail = (
            "Other recent reports disagree, but independent hazard data supports "
            "you, so the disagreement was set aside."
            if peers_disagree
            else "Nobody else has reported that road, but independent hazard data supports you."
        )
        return "corroborated", "independent_evidence", detail
    if peers_disagree:
        return (
            "contradicted",
            "peers",
            "Other recent reports on that road disagree, and no independent data backs you up.",
        )
    return (
        "no_consensus",
        "none",
        "Nobody else has reported that road recently and no independent data bears on it, so your score is unchanged.",
    )


def update_trust(
    db: Session,
    reporter: Reporter,
    report: FieldReport,
    *,
    independently_supported: bool = False,
) -> TrustUpdate:
    """Adjust the reporter's score, weighing peers and independent evidence.

    The API surfaces the whole result: a trust score that moves invisibly is
    the kind of thing people rightly distrust, and "why did my score drop"
    deserves a real answer.
    """
    peer_consensus = None
    if report.road_id is not None:
        others = recent_reports(db, report.road_id, exclude_id=report.id)
        peer_consensus = _consensus_of(others)

    outcome, basis, explanation = decide_outcome(
        peer_consensus, report.status, independently_supported
    )

    if outcome == "corroborated":
        reporter.times_corroborated += 1
    elif outcome == "contradicted":
        reporter.times_contradicted += 1

    agreed = reporter.times_corroborated
    disagreed = reporter.times_contradicted
    raw = NEUTRAL_TRUST + 0.5 * (agreed - disagreed) / (agreed + disagreed + PRIOR_WEIGHT)
    reporter.trust_score = round(min(TRUST_CEILING, max(TRUST_FLOOR, raw)), 4)

    return TrustUpdate(
        outcome=outcome,
        basis=basis,
        peer_consensus=peer_consensus,
        independently_supported=independently_supported,
        trust_score=reporter.trust_score,
        explanation=explanation,
    )


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
