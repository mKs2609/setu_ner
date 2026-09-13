"""
Train and evaluate the district flood-state model.

    cd apps/api
    python -m app.services.model.train
    python -m app.services.model.train --test-from 2026-01-01

Trains on every report before --test-from (the 2025 monsoon by default),
chooses between logistic regression and the two baselines on forward-chaining
validation folds inside that period, then evaluates once on the held-out
season. Writes one JSON artifact per horizon to ml/models/.

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
from app.services.model.dataset import build_examples
from app.services.model.history import load_history

DEFAULT_TEST_FROM = date(2026, 1, 1)


def _fmt(metrics: dict | None, part: str) -> str:
    if not metrics or not metrics.get(part) or not metrics[part].get("n"):
        return "n/a"
    m = metrics[part]
    auc = "-" if m["roc_auc"] is None else f"{m['roc_auc']:.3f}"
    return f"brier {m['brier']:.4f}  auc {auc}  (n={m['n']}, pos={m['positives']})"


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
        examples = build_examples(history, h)
        try:
            payload = dm.train_and_evaluate(examples, h, test_from)
        except ValueError as exc:
            print(f"\nh={h}: not trained -- {exc}")
            continue

        print(f"\n=== horizon {h} day(s): {payload['version']} ===")
        print(f"train  {payload['train_period']}")
        print(f"test   {payload['test_period']}")
        print(f"validation mean Brier: {payload['selection'].get('mean_brier')}")
        print(f"served: {payload['kind']}")
        tm = payload["test_metrics"]
        for name in ("served", "logistic", "persistence", "climatology"):
            print(f"  {name:12} all    {_fmt(tm.get(name), 'all')}")
            print(f"  {'':12} onset  {_fmt(tm.get(name), 'onset')}")
        print(f"verdict: {payload['verdict']['summary']}")

        if not args.dry_run:
            print(f"saved: {dm.save(payload)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
