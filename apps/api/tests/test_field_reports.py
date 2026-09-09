"""
Tests for the field-report fusion layer.

The pure-function half needs no database and runs in CI: the trust update,
the recency decay and the consensus rule are where the judgement lives, and
they are the parts a reviewer will actually challenge.

The integration half exercises snapping and fusion against the real corridor
and skips without a database.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.fusion import reports as fusion

client = TestClient(app)


@dataclass
class FakeReport:
    status: str
    trust_at_submission: float
    submitted_at: datetime = None  # type: ignore[assignment]


@dataclass
class FakeReporter:
    trust_score: float = fusion.NEUTRAL_TRUST
    times_corroborated: int = 0
    times_contradicted: int = 0


def apply_trust(agreed: int, disagreed: int) -> float:
    """The trust formula alone, so its shape can be asserted directly."""
    raw = fusion.NEUTRAL_TRUST + 0.5 * (agreed - disagreed) / (
        agreed + disagreed + fusion.PRIOR_WEIGHT
    )
    return round(min(fusion.TRUST_CEILING, max(fusion.TRUST_FLOOR, raw)), 4)


# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------


def test_new_reporter_starts_neutral_not_at_zero():
    """A newcomer's first report about a collapsed bridge should be visible,
    just not decisive."""
    assert apply_trust(0, 0) == fusion.NEUTRAL_TRUST


def test_agreeing_raises_and_contradicting_lowers():
    assert apply_trust(3, 0) > fusion.NEUTRAL_TRUST
    assert apply_trust(0, 3) < fusion.NEUTRAL_TRUST


def test_one_disagreement_cannot_destroy_a_good_record():
    """The prior damps the update, so a single contradiction after a long
    good run is a nudge rather than a cliff."""
    established = apply_trust(20, 0)
    after_one_miss = apply_trust(20, 1)
    assert after_one_miss < established
    assert established - after_one_miss < 0.05


def test_trust_is_bounded_at_both_ends():
    """Nobody reaches certainty and nobody is silenced completely -- a
    reporter who has been wrong before may be first to see something real."""
    assert apply_trust(10_000, 0) <= fusion.TRUST_CEILING
    assert apply_trust(0, 10_000) >= fusion.TRUST_FLOOR
    assert fusion.TRUST_FLOOR > 0


# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------


def test_consensus_needs_an_actual_majority():
    assert fusion._consensus_of([FakeReport("blocked", 0.5), FakeReport("blocked", 0.5)]) == "blocked"


def test_a_tie_is_no_consensus_rather_than_an_arbitrary_pick():
    """With one voice each way there is no ground truth to judge a new report
    against, so nobody's trust should move."""
    tied = [FakeReport("blocked", 0.5), FakeReport("clear", 0.5)]
    assert fusion._consensus_of(tied) is None


def test_consensus_is_weighted_by_trust_not_headcount():
    """Two low-trust reporters should not outvote one well-established one."""
    votes = [
        FakeReport("clear", 0.1),
        FakeReport("clear", 0.1),
        FakeReport("blocked", 0.9),
    ]
    assert fusion._consensus_of(votes) == "blocked"


def test_no_reports_means_no_consensus():
    assert fusion._consensus_of([]) is None


# ---------------------------------------------------------------------------
# Recency
# ---------------------------------------------------------------------------


def test_a_fresh_report_outweighs_an_old_one():
    """Roads get cleared. A 'blocked' from twenty hours ago is weaker evidence
    than one from twenty minutes ago."""
    now = datetime.now(timezone.utc)
    fresh = fusion._recency_weight(now, now)
    old = fusion._recency_weight(now - timedelta(hours=20), now)
    assert fresh > old


def test_a_report_inside_the_window_never_counts_for_nothing():
    now = datetime.now(timezone.utc)
    edge = fusion._recency_weight(
        now - timedelta(hours=fusion.FUSION_WINDOW_HOURS), now
    )
    assert edge > 0


def test_naive_timestamps_are_treated_as_utc_not_crashed_on():
    now = datetime.now(timezone.utc)
    naive = (now - timedelta(hours=1)).replace(tzinfo=None)
    assert 0 < fusion._recency_weight(naive, now) <= 1


# ---------------------------------------------------------------------------
# Configuration sanity
# ---------------------------------------------------------------------------


def test_snap_distance_guard_is_tight_enough_to_mean_something():
    """A report snapped kilometres away is a GPS error or an uncovered area,
    not an observation about that road."""
    assert 0 < fusion.MAX_SNAP_DISTANCE_M <= 1000


# ---------------------------------------------------------------------------
# API validation (no database needed)
# ---------------------------------------------------------------------------


def test_impossible_coordinates_are_rejected():
    r = client.post(
        "/api/v1/field-reports",
        json={
            "status": "blocked",
            "latitude": 999,
            "longitude": 92.7,
            "reporter_id": "device-test-001",
        },
    )
    assert r.status_code == 422


def test_unknown_status_is_rejected():
    r = client.post(
        "/api/v1/field-reports",
        json={
            "status": "on fire",
            "latitude": 24.8,
            "longitude": 92.7,
            "reporter_id": "device-test-001",
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM field_reports LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no field_reports table reachable (expected in CI)"
)


@needs_db
def test_report_near_a_road_snaps_to_it():
    r = client.post(
        "/api/v1/field-reports",
        json={
            "status": "slow",
            "latitude": 24.8333,
            "longitude": 92.7789,
            "reporter_id": "pytest-reporter-near",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["road_id"] is not None
    assert body["counted_in_fusion"] is True
    assert body["snapped_distance_m"] < fusion.MAX_SNAP_DISTANCE_M


@needs_db
def test_report_far_from_the_corridor_is_kept_but_not_counted():
    """Discarding it would hide that somebody is reporting from an area the
    road graph does not cover."""
    r = client.post(
        "/api/v1/field-reports",
        json={
            "status": "blocked",
            "latitude": 22.5726,
            "longitude": 88.3639,  # Kolkata, far outside the corridor
            "reporter_id": "pytest-reporter-far",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["road_id"] is None
    assert body["counted_in_fusion"] is False
    assert body["snapped_distance_m"] > fusion.MAX_SNAP_DISTANCE_M
    assert body["id"] is not None, "the report is still stored"


@needs_db
def test_fused_status_is_published_separately_from_the_baseline():
    """The whole point of the separation: a reader must be able to tell a
    crowd consensus from a historical score from a model prediction."""
    r = client.post(
        "/api/v1/field-reports",
        json={
            "status": "blocked",
            "latitude": 24.8333,
            "longitude": 92.7789,
            "reporter_id": "pytest-reporter-fuse",
        },
    )
    road_id = r.json()["road_id"]

    got = client.get(f"/api/v1/field-reports/road/{road_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["field_reported"]["status"] in {"clear", "slow", "blocked"}
    assert 0 <= body["field_reported"]["confidence"] <= 1
    assert "baseline_accessibility" in body["road"]
    assert "not_a_model_prediction" in body["caveats"]


@needs_db
def test_field_reports_never_write_current_accessibility():
    """current_accessibility is reserved for the Phase 3 model. A crowd vote
    must not be smuggled into it."""
    from sqlalchemy import func, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        populated = db.execute(
            select(func.count(Road.id)).where(Road.current_accessibility.isnot(None))
        ).scalar_one()
    assert populated == 0


@needs_db
def test_unknown_road_is_a_404():
    assert client.get("/api/v1/field-reports/road/99999999").status_code == 404


@needs_db
def test_recent_reports_can_be_filtered_by_status():
    r = client.get("/api/v1/field-reports/recent?status=blocked&limit=5")
    assert r.status_code == 200
    assert all(x["status"] == "blocked" for x in r.json()["reports"])
