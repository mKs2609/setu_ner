"""
Tests for corroborating field reports against independent hazard data.

The truth table for `decide_outcome` is the important part and runs without a
database. It encodes two claims that are easy to state and easy to get wrong:

  - Independent evidence can support a report but never counts against one.
  - Independent support outranks peer disagreement.

The second is the entire anti-collusion mechanism, so it is tested from every
direction rather than once.
"""


import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.fusion import corroboration as corrob
from app.services.fusion.reports import decide_outcome

client = TestClient(app)


# ---------------------------------------------------------------------------
# The trust rule, exhaustively
# ---------------------------------------------------------------------------


def test_peers_agree_and_evidence_supports():
    outcome, basis, _ = decide_outcome("blocked", "blocked", True)
    assert (outcome, basis) == ("corroborated", "both")


def test_peers_agree_without_evidence():
    outcome, basis, _ = decide_outcome("blocked", "blocked", False)
    assert (outcome, basis) == ("corroborated", "peers")


def test_lone_reporter_with_evidence_is_corroborated():
    """An honest reporter no longer needs company to build trust."""
    outcome, basis, _ = decide_outcome(None, "blocked", True)
    assert (outcome, basis) == ("corroborated", "independent_evidence")


def test_lone_reporter_without_evidence_is_left_alone():
    outcome, basis, _ = decide_outcome(None, "blocked", False)
    assert (outcome, basis) == ("no_consensus", "none")


def test_peers_disagree_without_evidence_is_a_contradiction():
    outcome, basis, _ = decide_outcome("clear", "blocked", False)
    assert (outcome, basis) == ("contradicted", "peers")


def test_independent_evidence_outranks_peer_disagreement():
    """THE anti-collusion property. A group can outvote a lone honest
    reporter; they cannot outvote a government damage bulletin."""
    outcome, basis, explanation = decide_outcome("clear", "blocked", True)
    assert outcome == "corroborated", "peers must not override real evidence"
    assert basis == "independent_evidence"
    assert "set aside" in explanation


def test_every_combination_is_covered_and_none_crashes():
    for peers in (None, "clear", "slow", "blocked"):
        for status in ("clear", "slow", "blocked"):
            for supported in (True, False):
                outcome, basis, explanation = decide_outcome(peers, status, supported)
                assert outcome in {"corroborated", "contradicted", "no_consensus"}
                assert basis in {"peers", "independent_evidence", "both", "none"}
                assert explanation


def test_a_report_is_never_penalised_for_lacking_evidence():
    """Absence of evidence is not evidence of absence: DRIMS is daily and
    district-level, and routinely behind what someone on the road can see.
    Only peers may ever produce a contradiction."""
    for peers in (None, "blocked"):
        for status in ("clear", "slow", "blocked"):
            outcome, _, _ = decide_outcome(peers, status, False)
            if peers is None or peers == status:
                assert outcome != "contradicted"


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def test_district_flood_impact_alone_does_not_corroborate_one_road():
    """A whole district being flood-affected says nothing specific about a
    single road. This boundary is the point of the weighting."""
    assert corrob.WEIGHT_DISTRICT_IMPACT < corrob.SUPPORT_THRESHOLD


def test_reported_infrastructure_damage_does_corroborate():
    assert corrob.WEIGHT_DISTRICT_INFRASTRUCTURE >= corrob.SUPPORT_THRESHOLD


def test_a_nearby_damage_point_is_the_strongest_evidence():
    assert (
        corrob.WEIGHT_DAMAGE_POINT
        > corrob.WEIGHT_DISTRICT_INFRASTRUCTURE
        > corrob.WEIGHT_DISTRICT_IMPACT
    )


def test_evidence_window_is_wider_than_the_peer_window():
    """DRIMS publishes daily and districts submit late, so independent
    evidence has to be allowed to be older than a peer report."""
    from app.services.fusion.reports import FUSION_WINDOW_HOURS

    assert corrob.EVIDENCE_WINDOW_HOURS > FUSION_WINDOW_HOURS


# ---------------------------------------------------------------------------
# Integration -- real corridor data
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM hazard_observations LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no hazard data reachable (expected in CI)"
)


@needs_db
def test_clear_reports_get_neutral_treatment_not_contradiction():
    """A road can be perfectly passable in a district that is flooding
    elsewhere. Accurate good news must not be scored against."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = corrob.corroborate(
            db, road_id=29408, district="Cachar", status="clear", window_hours=24 * 365
        )
    assert result.supports is False
    assert result.score == 0.0
    assert "neutral" in result.note


@needs_db
def test_unsnapped_report_has_nothing_to_match_against():
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = corrob.corroborate(
            db, road_id=None, district=None, status="blocked"
        )
    assert result.supports is False
    assert "snapped to no road" in result.note


@needs_db
def test_a_nearby_damage_point_produces_support():
    """Road 45306 in Cachar has a DRIMS damage point ~36 m away. With a window
    wide enough to include it, that must register as support."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = corrob.corroborate(
            db,
            road_id=45306,
            district="Cachar",
            status="blocked",
            window_hours=24 * 365,
        )
    kinds = {e.kind for e in result.evidence}
    assert "damage_point_nearby" in kinds
    assert result.supports is True
    assert result.score >= corrob.WEIGHT_DAMAGE_POINT


@needs_db
def test_a_tight_window_excludes_stale_evidence():
    """Old damage must not corroborate today's report just because it exists."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        recent = corrob.corroborate(
            db, road_id=45306, district="Cachar", status="blocked", window_hours=1
        )
    assert recent.score == 0.0
    assert "No independent evidence" in recent.note


@needs_db
def test_submitting_a_report_returns_its_evidence_and_reasoning():
    r = client.post(
        "/api/v1/field-reports",
        json={
            "status": "blocked",
            "latitude": 24.8333,
            "longitude": 92.7789,
            "reporter_id": "pytest-corroboration-001",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["trust_outcome"] in {"corroborated", "contradicted", "no_consensus"}
    assert body["trust_basis"] in {"peers", "independent_evidence", "both", "none"}
    assert body["trust_explanation"]
    ev = body["independent_evidence"]
    assert "score" in ev and "supports" in ev and "evidence" in ev
    assert "never counts against" in ev["caveat"]


@needs_db
def test_road_view_publishes_independent_evidence():
    r = client.get("/api/v1/field-reports/road/29408")
    assert r.status_code == 200
    body = r.json()
    assert "independent_evidence" in body
    assert "collusion" in body["caveats"]
