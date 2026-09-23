"""
The shadow test: a challenger model forecasts every day beside the served one,
and is graded only on days neither has seen.

WHY THIS EXISTS
The rainfall model beat the served one on the 2026 test season but lost on
the 2025 validation folds the selection rule chooses with (docs/decisions/
0014). Changing the rule after seeing the test would make the test part of
the choice. So the 2026 numbers cannot promote it -- only new days can.

WHAT IS FIXED IN ADVANCE, AND WHERE
Everything that decides the outcome is written into the challenger artifact
when it is frozen, before any shadow forecast exists:

  * the model itself (features, coefficients) -- never retrained in place
  * `frozen_on` -- only reports dated on or after it are graded
  * `promotion_rule` -- the sample size and the bootstrap test below

Changing any of these means freezing a new challenger, whose clock starts
again. That is the price of the result meaning something.

WHAT IS COMPARED
Pairs: for each (district, report day, horizon) with both a served and a
shadow forecast and a published outcome, the two Brier scores. A shadow row
is only stored when the challenger had every input (rain can be late); a
fallback row would be persistence wearing the challenger's name, and would
drag its score toward the baseline it is supposed to be beating.

WHAT IT DOES NOT DO
Promote anything. The verdict says what the rule concluded; swapping the
served artifact is a deliberate act, recorded in the decision log.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import and_, not_, select

from app.db.models import DistrictFloodForecast
from app.services.model import district_model as dm
from app.services.model.dataset import Example

CHALLENGER_NAME = "district_flood_state_h{h}_challenger.json"

# Every row the challenger writes carries this prefix in model_kind, which is
# how every reader of district_flood_forecasts tells served rows from shadow.
SHADOW_KIND_PREFIX = "shadow_"

# Fixed before any shadow data exists (22 Sep 2026). See module docstring.
PROMOTION_RULE = {
    "min_pairs": 1500,
    # Pairs where the district was not affected on the report day and was
    # affected on the target day: floods that actually began. A quiet season
    # supplies thousands of not-affected days with nothing to learn from.
    "min_flood_onsets": 30,
    "bootstrap": "resample report days with replacement, 2000 times, seed 0",
    "interval": 0.90,
    "promote_if": "the whole 90% interval of Brier(served) - Brier(challenger) is above 0",
    "reject_if": "the whole 90% interval is below 0",
    "otherwise": "undecided -- keep collecting",
}
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 0


def challenger_path(horizon_days: int) -> Path:
    return dm.ARTIFACT_DIR / CHALLENGER_NAME.format(h=horizon_days)


def load_challenger(horizon_days: int, path: Path | None = None) -> dict | None:
    return dm.load(horizon_days, path or challenger_path(horizon_days))


def served_only():
    """SQL condition selecting the served model's stored forecasts."""
    return not_(
        DistrictFloodForecast.model_kind.startswith(SHADOW_KIND_PREFIX, autoescape=True)
    )


def shadow_only():
    return DistrictFloodForecast.model_kind.startswith(SHADOW_KIND_PREFIX, autoescape=True)


# ---------------------------------------------------------------------------
# Freezing a challenger
# ---------------------------------------------------------------------------


def make_challenger(
    examples: list[Example],
    horizon_days: int,
    test_from: date,
    features: tuple[str, ...],
    frozen_on: date,
) -> dict:
    """The logistic model on `features`, even if validation preferred a
    baseline -- being tested is the point. Its C is still the one validation
    chose among logistic candidates, so no test number enters the fit."""
    base = dm.train_and_evaluate(examples, horizon_days, test_from, features)
    logistic = {
        k: v for k, v in base["selection"]["mean_brier"].items() if k.startswith("logistic_C")
    }
    if not logistic:
        raise ValueError("no validated logistic candidate to freeze")
    best = min(logistic, key=logistic.get)
    c = float(best.split("_C", 1)[1])

    train = [e for e in examples if e.target_date < test_from]
    predictor = dm.fit_logistic(train, c)
    digest = hashlib.sha256(
        json.dumps([features, predictor.params], sort_keys=True).encode()
    ).hexdigest()[:8]
    return {
        **base,
        "role": "challenger",
        "kind": "logistic",
        "params": predictor.params,
        "selection": {**base["selection"], "challenger_selected": best},
        "test_metrics": {**base["test_metrics"], "served": base["test_metrics"].get("logistic")},
        "version": f"dfs-h{horizon_days}-shadow-{frozen_on.isoformat()}-{digest}",
        "frozen_on": frozen_on.isoformat(),
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "promotion_rule": PROMOTION_RULE,
        "verdict": {
            "summary": (
                "Challenger, not served. Graded live against the served model on "
                f"reports dated {frozen_on.isoformat()} or later."
            )
        },
    }


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------


def shadow_rows(rows: list[dict]) -> list[dict]:
    """Challenger forecasts ready to store: fallback rows dropped, the rest
    marked as shadow."""
    out = []
    for r in rows:
        if r["model_kind"] == "persistence_fallback":
            continue
        out.append({**r, "model_kind": SHADOW_KIND_PREFIX + r["model_kind"]})
    return out


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def pair_forecasts(served, shadow, frozen_on: date, outcome) -> list[dict]:
    """Match each shadow forecast to the served forecast it competed with.

    `served` and `shadow` are stored forecast rows; `outcome(district, day)`
    returns True/False, or None when that day's report is not published.
    The newest row wins where a day was scored more than once.
    """
    def newest(rows):
        best = {}
        for r in rows:
            k = (r.district_key, r.as_of_date, r.horizon_days)
            if k not in best or r.created_at > best[k].created_at:
                best[k] = r
        return best

    served_by, shadow_by = newest(served), newest(shadow)
    pairs = []
    for k, sh in shadow_by.items():
        sv = served_by.get(k)
        if sv is None or sh.as_of_date < frozen_on:
            continue
        y = outcome(sh.district_key, sh.target_date)
        if y is None:
            continue
        pairs.append(
            {
                "day": sh.as_of_date,
                "y": int(y),
                "onset": not sh.affected_on_as_of,
                "served": sv.probability,
                "shadow": sh.probability,
                "persistence": sv.persistence_probability,
            }
        )
    return pairs


def verdict(pairs: list[dict], rule: dict = PROMOTION_RULE) -> dict:
    """Apply the frozen rule to the pairs collected so far."""
    n = len(pairs)
    onsets = [p for p in pairs if p["onset"]]
    positives_at_onset = sum(p["y"] for p in onsets)
    out = {
        "pairs": n,
        "onset_pairs": len(onsets),
        "onsets_that_flooded": positives_at_onset,
        "rule": rule,
    }
    if n == 0:
        return {**out, "decision": "undecided", "reason": "no graded pairs yet"}

    y = np.array([p["y"] for p in pairs], dtype=float)
    served = np.array([p["served"] for p in pairs])
    shadow = np.array([p["shadow"] for p in pairs])
    pers = np.array([p["persistence"] for p in pairs])
    out["brier"] = {
        "served": round(float(np.mean((served - y) ** 2)), 5),
        "challenger": round(float(np.mean((shadow - y) ** 2)), 5),
        "persistence": round(float(np.mean((pers - y) ** 2)), 5),
    }
    if onsets:
        yo = np.array([p["y"] for p in onsets], dtype=float)
        out["onset_brier"] = {
            "served": round(float(np.mean((np.array([p["served"] for p in onsets]) - yo) ** 2)), 5),
            "challenger": round(float(np.mean((np.array([p["shadow"] for p in onsets]) - yo) ** 2)), 5),
        }

    if n < rule["min_pairs"] or positives_at_onset < rule["min_flood_onsets"]:
        return {
            **out,
            "decision": "undecided",
            "reason": (
                f"{n}/{rule['min_pairs']} pairs and {positives_at_onset}/{rule['min_flood_onsets']} "
                "flood onsets so far; the rule needs both before it decides anything"
            ),
        }

    lo, hi = bootstrap_interval(pairs, rule["interval"])
    out["improvement_interval"] = [round(lo, 5), round(hi, 5)]
    if lo > 0:
        decision, reason = "promote", "the challenger is better across the whole interval"
    elif hi < 0:
        decision, reason = "reject", "the challenger is worse across the whole interval"
    else:
        decision, reason = "undecided", "the interval includes no difference; keep collecting"
    return {**out, "decision": decision, "reason": reason}


def bootstrap_interval(pairs: list[dict], level: float) -> tuple[float, float]:
    """Interval for mean Brier(served) - Brier(challenger), resampling whole
    report days: the districts of one day share its weather, so they are not
    independent, and resampling rows would make the interval too narrow."""
    by_day: dict[date, list[float]] = {}
    for p in pairs:
        diff = (p["served"] - p["y"]) ** 2 - (p["shadow"] - p["y"]) ** 2
        by_day.setdefault(p["day"], []).append(diff)
    days = list(by_day.values())
    sums = np.array([sum(d) for d in days])
    counts = np.array([len(d) for d in days])

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = rng.integers(0, len(days), size=(BOOTSTRAP_RESAMPLES, len(days)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    tail = (1 - level) / 2
    return float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def track_record(db, history) -> dict:
    """The shadow test's current state, per horizon."""
    out = {}
    for h in dm.HORIZONS:
        challenger = load_challenger(h)
        if challenger is None:
            out[str(h)] = {"status": "no challenger frozen"}
            continue
        frozen_on = date.fromisoformat(challenger["frozen_on"])
        served = db.execute(
            select(DistrictFloodForecast).where(
                and_(served_only(), DistrictFloodForecast.horizon_days == h,
                     DistrictFloodForecast.as_of_date >= frozen_on)
            )
        ).scalars().all()
        shadow = db.execute(
            select(DistrictFloodForecast).where(
                and_(shadow_only(), DistrictFloodForecast.horizon_days == h,
                     DistrictFloodForecast.model_version == challenger["version"])
            )
        ).scalars().all()

        def outcome(district, day):
            s = history.state(district, day)
            return None if s is None else s.affected

        pairs = pair_forecasts(served, shadow, frozen_on, outcome)
        out[str(h)] = {
            "challenger_version": challenger["version"],
            "features": challenger["features"],
            "frozen_on": challenger["frozen_on"],
            "shadow_forecasts_stored": len(shadow),
            **verdict(pairs, challenger.get("promotion_rule", PROMOTION_RULE)),
        }
    return out
