"""
Tests for the shadow test.

What could go wrong silently: a shadow forecast leaking onto the map or into
the served track record; a fallback row graded as the challenger's own work;
days from before the freeze counted; a verdict reached on too little data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services.model import shadow
from app.services.model.dataset import FEATURES, RAIN_FEATURES, build_examples, build_history

client = TestClient(app)
D0 = date(2026, 10, 1)
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


@dataclass
class Row:
    district_key: str
    as_of_date: date
    horizon_days: int
    target_date: date
    probability: float
    persistence_probability: float
    affected_on_as_of: bool
    created_at: datetime


def row(d, day, p, created=0, affected=False, pers=0.05):
    return Row(d, day, 1, day + timedelta(days=1), p, pers, affected, T0 + timedelta(minutes=created))


# ---------------------------------------------------------------------------
# What gets stored
# ---------------------------------------------------------------------------


def test_fallback_rows_are_not_stored_as_the_challengers_work():
    """A row served by persistence because rain was late would pull the
    challenger's score toward the baseline it is meant to beat."""
    rows = [
        {"district_key": "a", "model_kind": "logistic"},
        {"district_key": "b", "model_kind": "persistence_fallback"},
    ]
    out = shadow.shadow_rows(rows)
    assert [r["district_key"] for r in out] == ["a"]
    assert out[0]["model_kind"] == "shadow_logistic"


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def test_only_pairs_after_the_freeze_with_a_known_outcome_are_graded():
    served = [row("a", D0 - timedelta(days=1), 0.2), row("a", D0, 0.2), row("a", D0 + timedelta(days=1), 0.2)]
    shadow_rows = [row("a", D0 - timedelta(days=1), 0.9), row("a", D0, 0.9), row("a", D0 + timedelta(days=1), 0.9)]
    outcome = lambda d, day: None if day == D0 + timedelta(days=2) else True  # noqa: E731
    pairs = shadow.pair_forecasts(served, shadow_rows, D0, outcome)
    assert [p["day"] for p in pairs] == [D0]  # before freeze dropped; unknown outcome dropped


def test_a_shadow_row_without_a_served_partner_is_not_graded():
    pairs = shadow.pair_forecasts([], [row("a", D0, 0.9)], D0, lambda d, day: True)
    assert pairs == []


def test_the_newest_row_wins_when_a_day_was_scored_twice():
    served = [row("a", D0, 0.1, created=0), row("a", D0, 0.3, created=5)]
    shadow_rows = [row("a", D0, 0.7, created=0), row("a", D0, 0.8, created=9)]
    (p,) = shadow.pair_forecasts(served, shadow_rows, D0, lambda d, day: True)
    assert (p["served"], p["shadow"]) == (0.3, 0.8)


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def _pairs(days, per_day, shadow_better: bool, flood_every=10, seed=0):
    """Synthetic pairs. Floods start on some not-affected days; the better
    model puts more probability on them."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(days):
        for j in range(per_day):
            y = int(rng.random() < 1 / flood_every)
            good = 0.6 if y else 0.03
            bad = 0.2 if y else 0.08
            s, v = (good, bad) if shadow_better else (bad, good)
            out.append({"day": D0 + timedelta(days=i), "y": y, "onset": True,
                        "served": v, "shadow": s, "persistence": 0.05})
    return out


def test_no_decision_before_the_minimums_however_good_it_looks():
    pairs = _pairs(days=10, per_day=30, shadow_better=True)  # 300 pairs
    v = shadow.verdict(pairs)
    assert v["brier"]["challenger"] < v["brier"]["served"]
    assert v["decision"] == "undecided"
    assert "1500" in v["reason"]


def test_flood_onsets_count_only_floods_that_began():
    """Thousands of quiet days must not satisfy the onset minimum."""
    quiet = [{"day": D0 + timedelta(days=i // 34), "y": 0, "onset": True,
              "served": 0.05, "shadow": 0.04, "persistence": 0.05} for i in range(3400)]
    v = shadow.verdict(quiet)
    assert v["onset_pairs"] == 3400 and v["onsets_that_flooded"] == 0
    assert v["decision"] == "undecided"


def test_a_clearly_better_challenger_is_promoted_and_a_worse_one_rejected():
    assert shadow.verdict(_pairs(60, 34, shadow_better=True))["decision"] == "promote"
    assert shadow.verdict(_pairs(60, 34, shadow_better=False))["decision"] == "reject"


def test_identical_models_stay_undecided():
    pairs = _pairs(60, 34, shadow_better=True)
    for p in pairs:
        p["shadow"] = p["served"]
    assert shadow.verdict(pairs)["decision"] == "undecided"


def test_the_bootstrap_is_reproducible():
    pairs = _pairs(60, 34, shadow_better=True)
    assert shadow.bootstrap_interval(pairs, 0.9) == shadow.bootstrap_interval(pairs, 0.9)


# ---------------------------------------------------------------------------
# Freezing
# ---------------------------------------------------------------------------


def _history_with_rain(days=120, districts=6, seed=0):
    rng = np.random.default_rng(seed)
    published = [D0 + timedelta(days=i) for i in range(days)]
    obs = []
    for d in range(districts):
        affected = False
        for i in range(days):
            affected = rng.random() < (0.85 if affected else 0.05)
            if affected:
                obs.append((published[i], f"District{d}", "population_affected", 100.0))
    h = build_history(published, obs)
    for key in h.districts:
        for i in range(-8, days):
            h.rainfall[(key, D0 + timedelta(days=i))] = float(rng.gamma(1.0, 10.0))
    return h


def test_the_challenger_is_the_rain_logistic_even_if_validation_preferred_a_baseline():
    feats = FEATURES + RAIN_FEATURES
    ex = build_examples(_history_with_rain(), 1, features=feats)
    c = shadow.make_challenger(ex, 1, D0 + timedelta(days=90), feats, frozen_on=date(2026, 9, 22))
    assert c["role"] == "challenger" and c["kind"] == "logistic"
    assert c["features"] == list(feats)
    assert c["frozen_on"] == "2026-09-22"
    assert "-shadow-" in c["version"]
    assert c["promotion_rule"] == shadow.PROMOTION_RULE
    assert c["selection"]["challenger_selected"].startswith("logistic_C")


# ---------------------------------------------------------------------------
# Nothing public shows a shadow forecast -- against the real database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM district_flood_forecasts LIMIT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="no corridor database (expected in CI)")
def test_a_shadow_forecast_never_reaches_the_map_or_the_served_record():
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        latest = db.execute(text(
            "SELECT max(as_of_date) FROM district_flood_forecasts WHERE model_kind NOT LIKE 'shadow\\_%'"
        )).scalar()
        if latest is None:
            pytest.skip("no served forecasts stored")
        db.execute(text("""
            INSERT INTO district_flood_forecasts
              (district_key, display_name, in_corridor, as_of_date, target_date, horizon_days,
               probability, persistence_probability, affected_on_as_of, model_version,
               model_kind, created_at)
            VALUES ('Cachar', 'Cachar', true, :d, :t, 1, 0.999, 0.5, false,
                    'test-shadow-sentinel', 'shadow_logistic', now() + interval '1 day')
        """), {"d": latest, "t": latest + timedelta(days=1)})
        db.commit()
    try:
        body = client.get("/api/v1/model/districts").json()
        cachar = [d for d in body["districts"] if d["district"] == "Cachar"][0]
        h1 = [f for f in cachar["forecasts"] if f["horizon_days"] == 1][0]
        assert h1["probability"] != 0.999
        assert not h1["model_kind"].startswith("shadow_")

        status = client.get("/api/v1/model/status").json()
        assert "shadow_test" in status
    finally:
        with SessionLocal() as db:
            db.execute(text(
                "DELETE FROM district_flood_forecasts WHERE model_version = 'test-shadow-sentinel'"
            ))
            db.commit()
