"""
Train and evaluate the district flood-state model.

    cd apps/api
    python -m app.services.model.train
    python -m app.services.model.train --test-from 2026-01-01

Trains on every report before --test-from (the 2025 monsoon by default),
chooses between logistic regression and the two baselines on forward-chaining
validation folds inside that period, then evaluates once on the held-out
season. Writes one JSON artifact per horizon to ml/models/.

WITH OR WITHOUT RAINFALL
When rainfall has been ingested, each horizon is trained twice -- with the
report features alone, and with rainfall added -- on exactly the same rows.
The one with the lower *validation* Brier is saved. Both are then shown on the
test season, marked as not used for choosing: picking whichever looked better
on test would make the test number a training number.

Re-running on the same data produces the same coefficients. Running after
another season has been ingested produces a new version with new test
numbers -- which is the point of versioning it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from app.db.session import SessionLocal
from app.services.model import district_model as dm
from app.services.model.dataset import FEATURES, RAIN_FEATURES, build_examples
from app.services.model.history import load_history

DEFAULT_TEST_FROM = date(2026, 1, 1)


def _fmt(metrics: dict | None, part: str) -> str:
    if not metrics or not metrics.get(part) or not metrics[part].get("n"):
        return "n/a"
    m = metrics[part]
    auc = "-" if m["roc_auc"] is None else f"{m['roc_auc']:.3f}"
    return f"brier {m['brier']:.4f}  auc {auc}  (n={m['n']}, pos={m['positives']})"


def _validation_brier(payload: dict) -> float:
    """The validation score of the predictor this payload serves."""
    sel = payload["selection"]
    return sel["mean_brier"].get(sel.get("selected"), float("inf"))


def _report(h: int, name: str, payload: dict) -> None:
    print(f"\n=== horizon {h} day(s), {name}: {payload['version']} ===")
    print(f"train  {payload['train_period']}")
    print(f"test   {payload['test_period']}")
    print(f"validation Brier of served: {_validation_brier(payload):.5f}")
    print(f"served: {payload['kind']}")
    tm = payload["test_metrics"]
    for kind in ("served", "logistic", "persistence", "climatology"):
        print(f"  {kind:12} all    {_fmt(tm.get(kind), 'all')}")
        print(f"  {'':12} onset  {_fmt(tm.get(kind), 'onset')}")
    print(f"verdict: {payload['verdict']['summary']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the district flood-state model.")
    parser.add_argument("--test-from", default=DEFAULT_TEST_FROM.isoformat())
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without saving.")
    args = parser.parse_args(argv)
    test_from = date.fromisoformat(args.test_from)

    with SessionLocal() as db:
        history = load_history(db)
    print(
        f"history: {len(history.published)} published report days, "
        f"{len(history.districts)} districts"
    )

    for h in dm.HORIZONS:
        candidates = {}
        with_rain = build_examples(history, h, features=FEATURES + RAIN_FEATURES)
        if with_rain:
            same_rows = build_examples(history, h, features=FEATURES, only_where=RAIN_FEATURES)
            for name, ex, feats in (
                ("reports only", same_rows, FEATURES),
                ("reports + rainfall", with_rain, FEATURES + RAIN_FEATURES),
            ):
                try:
                    candidates[name] = dm.train_and_evaluate(ex, h, test_from, feats)
                except ValueError as exc:
                    print(f"\nh={h} {name}: not trained -- {exc}")
        else:
            print(f"\nh={h}: no rainfall ingested; training on report features only")
            try:
                candidates["reports only"] = dm.train_and_evaluate(
                    build_examples(history, h), h, test_from
                )
            except ValueError as exc:
                print(f"\nh={h}: not trained -- {exc}")
        if not candidates:
            continue

        for name, payload in candidates.items():
            _report(h, name, payload)

        chosen_name = min(candidates, key=lambda n: _validation_brier(candidates[n]))
        payload = candidates[chosen_name]
        if len(candidates) > 1:
            print(
                f"\nh={h}: chose '{chosen_name}' on validation Brier ("
                + ", ".join(f"{n} {_validation_brier(c):.5f}" for n, c in candidates.items())
                + "). Test numbers above were not used to choose."
            )
        payload["feature_set"] = chosen_name
        if not args.dry_run:
            print(f"saved: {dm.save(payload)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
