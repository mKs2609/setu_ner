"""
Measure whether the served model's probabilities mean what they say.

    cd apps/api
    python -m app.services.model.calibrate
    python -m app.services.model.calibrate --dry-run

Writes `ml/models/calibration_h{1,3}.json`, which the status endpoint serves
and the accessibility page draws as a reliability diagram.

WHY THIS IS NOT PART OF TRAINING
It would be the obvious place -- `evaluate()` already walks the held-out
season -- but putting it there would mean the numbers only appear by
retraining, and the retrain procedure is deliberately fixed until after the
season (`docs/retraining.md`). Calibration is a question about the model that
is *already* serving, so it is asked of that model, separately, and nothing
here writes a model artifact or changes a coefficient.

HOW IT AVOIDS MOVING THE GOALPOSTS
The test window is not chosen here. Each artifact records the period it was
evaluated on, and this reads that period back out and rebuilds exactly those
district-days. So the calibration describes the same forecasts the published
Brier and AUC describe -- not a window picked afterwards that happens to
look better.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from app.db.session import SessionLocal
from app.services.model import district_model as dm
from app.services.model.dataset import build_examples
from app.services.model.history import load_history

CALIBRATION_NAME = "calibration_h{h}.json"


def calibration_path(horizon_days: int):
    return dm.ARTIFACT_DIR / CALIBRATION_NAME.format(h=horizon_days)


def for_horizon(history, horizon_days: int) -> dict | None:
    """Calibration of the served artifact over the season it was tested on."""
    payload = dm.load(horizon_days)
    if payload is None:
        print(f"h={horizon_days}: no served artifact")
        return None

    period = payload.get("test_period") or {}
    if not period.get("from") or not period.get("to"):
        print(f"h={horizon_days}: artifact records no test period")
        return None
    start, end = date.fromisoformat(period["from"]), date.fromisoformat(period["to"])

    # The artifact's own feature list, so a challenger-shaped artifact would
    # be rebuilt with the inputs it was actually trained on.
    features = tuple(payload.get("features") or dm.FEATURES)
    examples = [
        e for e in build_examples(history, horizon_days, features=features)
        if start <= e.as_of <= end
    ]
    if not examples:
        print(f"h={horizon_days}: no examples in {start}..{end}")
        return None

    X, y, affected = dm._arrays(examples)
    p = dm.predictor_from(payload).predict(X, affected)

    result = dm.calibration(y, p)
    result["horizon_days"] = horizon_days
    result["model_version"] = payload["version"]
    result["served_kind"] = payload["kind"]
    result["period"] = {"from": start.isoformat(), "to": end.isoformat()}
    result["edges"] = list(dm.CALIBRATION_EDGES)
    result["measured_at"] = date.today().isoformat()

    # The window is the artifact's, but the rows are rebuilt from history as
    # it stands today -- and history has been repaired since training (a
    # district name broken by the PDF text layer, population reparsed). So
    # the count can differ slightly from the one the artifact recorded, and
    # pretending otherwise would quietly overstate how exactly these numbers
    # line up with the published Brier.
    at_training = (payload.get("test_period") or {}).get("examples")
    result["rows"] = {
        "now": result["n"],
        "at_training": at_training,
        "note": (
            None
            if at_training in (None, result["n"])
            else (
                f"{result['n']} rows rebuilt from current history against "
                f"{at_training} at training time; the report record has been "
                "repaired since (see services/ingestion/renormalise_districts.py)."
            )
        ),
    }
    return result


def describe(result: dict) -> str:
    d = result["decomposition"]
    lines = [
        f"\n=== horizon {result['horizon_days']} day(s) · {result['model_version']} "
        f"({result['served_kind']}) ===",
        f"{result['period']['from']} to {result['period']['to']}  "
        f"n={result['n']}  positives={result['positives']}  "
        f"base rate {result['base_rate']:.4f}",
        f"brier {d['brier']:.5f} = reliability {d['reliability']:.6f} "
        f"- resolution {d['resolution']:.6f} + uncertainty {d['uncertainty']:.5f} "
        f"(residual {d['residual']:+.6f})",
    ]
    if result["rows"].get("note"):
        lines.append(f"note: {result['rows']['note']}")
    lines += ["", f"  {'band':>13}  {'n':>6}  {'said':>8}  {'happened':>9}"]
    for b in result["bins"]:
        if not b["n"]:
            continue
        lines.append(
            f"  {b['from']:.2f}-{b['to']:.2f}  {b['n']:6d}  "
            f"{b['predicted']:8.4f}  {b['observed']:9.4f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print without writing.")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        history = load_history(db)
    print(f"history: {len(history.published)} published report days")

    written = 0
    for horizon in dm.HORIZONS:
        result = for_horizon(history, horizon)
        if result is None:
            continue
        print(describe(result))
        if not args.dry_run:
            path = calibration_path(horizon)
            path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"\nsaved: {path}")
            written += 1

    return 0 if (written or args.dry_run) else 1


if __name__ == "__main__":
    raise SystemExit(main())
