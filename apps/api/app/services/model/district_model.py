"""
Training, evaluating and serving the district flood-state model.

THE BAR IT HAS TO CLEAR
Flood state is sticky: a district affected today is very likely affected
tomorrow. So "the model is 90% accurate" means nothing on its own -- simply
repeating today's answer scores about that. Every metric here is reported
next to two baselines, and the served predictor is whichever of them wins on
*validation* data:

  climatology   the training base rate, the same for every district
  persistence   P(affected tomorrow | affected today), two numbers learned
                from training data

If the logistic model does not beat persistence, persistence is served and
the status endpoint says so. A model that loses to its own baseline is not a
model worth shipping just because it was built.

The hard part is **onset** -- a district that is not affected today becoming
affected. Persistence cannot see that coming by construction, so onset
performance is reported separately; it is where any real skill has to show.

WHY THE ARTIFACT IS JSON
The fitted model is a scaler and a dozen coefficients. Saving it as JSON
rather than a pickle means loading it cannot execute code, the numbers are
readable in a code review, and the API can serve it with numpy alone.

WHAT IS HONESTLY MISSING
Rainfall. Every free daily source tried (NASA POWER, Open-Meteo, CHIRPS)
disallows automated access in robots.txt, and this project respects that.
Without rainfall the model sees a flood only once it is reported, so onset
skill is expected to be weak. See docs/decisions/0010.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from app.services.model.dataset import FEATURES, Example

# ml/models at the repo root. Overridable because a container that copies only
# apps/api has no repo root above it.
ARTIFACT_DIR = Path(
    os.environ.get("SETUNER_MODEL_DIR")
    or Path(__file__).resolve().parents[5] / "ml" / "models"
)
ARTIFACT_NAME = "district_flood_state_h{h}.json"
HORIZONS = (1, 3)

# Probabilities are clipped away from 0 and 1. A district is never certainly
# dry or certainly flooded, and log loss is undefined at the edges.
EPS = 1e-3


def artifact_path(horizon_days: int) -> Path:
    return ARTIFACT_DIR / ARTIFACT_NAME.format(h=horizon_days)


# ---------------------------------------------------------------------------
# Predictors
# ---------------------------------------------------------------------------


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class Predictor:
    kind: str                     # logistic | persistence | climatology
    params: dict

    def predict(self, X: np.ndarray, affected_today: np.ndarray) -> np.ndarray:
        if self.kind == "logistic":
            mean = np.asarray(self.params["scaler_mean"])
            scale = np.asarray(self.params["scaler_scale"])
            coef = np.asarray(self.params["coef"])
            z = ((X - mean) / scale) @ coef + self.params["intercept"]
            p = _sigmoid(z)
        elif self.kind == "persistence":
            p = np.where(
                affected_today == 1,
                self.params["p_given_affected"],
                self.params["p_given_not_affected"],
            ).astype(float)
        elif self.kind == "climatology":
            p = np.full(len(affected_today), self.params["base_rate"], dtype=float)
        else:
            raise ValueError(f"unknown predictor kind {self.kind!r}")
        return np.clip(p, EPS, 1 - EPS)


def _arrays(examples: list[Example]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.asarray([e.x for e in examples], dtype=float).reshape(-1, len(FEATURES))
    y = np.asarray([e.y for e in examples], dtype=int)
    a = np.asarray([e.affected_today for e in examples], dtype=int)
    return X, y, a


def fit_climatology(examples: list[Example]) -> Predictor:
    _, y, _ = _arrays(examples)
    return Predictor("climatology", {"base_rate": float(y.mean()) if len(y) else 0.5})


def fit_persistence(examples: list[Example]) -> Predictor:
    """Laplace-smoothed, so a split with no transitions does not produce a
    confident 0 or 1."""
    _, y, a = _arrays(examples)

    def rate(mask: np.ndarray) -> float:
        return float((y[mask].sum() + 1) / (mask.sum() + 2))

    return Predictor(
        "persistence",
        {"p_given_affected": rate(a == 1), "p_given_not_affected": rate(a == 0)},
    )


def fit_logistic(examples: list[Example], C: float) -> Predictor:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X, y, _ = _arrays(examples)
    scaler = StandardScaler().fit(X)
    scale = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    clf = LogisticRegression(C=C, max_iter=2000).fit((X - scaler.mean_) / scale, y)
    return Predictor(
        "logistic",
        {
            "C": C,
            "scaler_mean": scaler.mean_.round(6).tolist(),
            "scaler_scale": scale.round(6).tolist(),
            "coef": clf.coef_[0].round(6).tolist(),
            "intercept": round(float(clf.intercept_[0]), 6),
        },
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """ROC AUC by rank; None when only one class is present."""
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sorted_p = p[order]
    i = 0
    while i < len(p):  # average ranks over ties
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def _average_precision(y: np.ndarray, p: np.ndarray) -> float | None:
    if y.sum() == 0:
        return None
    order = np.argsort(-p, kind="mergesort")
    hits = y[order]
    precision = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float((precision * hits).sum() / hits.sum())


def score(y: np.ndarray, p: np.ndarray) -> dict:
    if len(y) == 0:
        return {"n": 0}
    p = np.clip(p, EPS, 1 - EPS)
    return {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "brier": round(float(np.mean((p - y) ** 2)), 5),
        "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 5),
        "roc_auc": None if (v := _auc(y, p)) is None else round(v, 4),
        "average_precision": None if (v := _average_precision(y, p)) is None else round(v, 4),
    }


def evaluate(predictor: Predictor, examples: list[Example]) -> dict:
    """Overall, plus onset (not affected today) and recession (affected today).

    Onset is split out because persistence is blind to it by construction --
    that subset is where a model has to earn its place.
    """
    X, y, a = _arrays(examples)
    p = predictor.predict(X, a)
    return {
        "all": score(y, p),
        "onset": score(y[a == 0], p[a == 0]),
        "recession": score(y[a == 1], p[a == 1]),
    }


# ---------------------------------------------------------------------------
# Selection and training
# ---------------------------------------------------------------------------

C_GRID = (0.01, 0.1, 1.0, 10.0)


def rolling_validation(examples: list[Example], folds: int = 3) -> list[tuple[list, list]]:
    """Forward-chaining splits by date: always train on the past, validate on
    what came after. Shuffled k-fold would leak tomorrow into yesterday,
    because adjacent days of one flood are nearly identical rows."""
    days = sorted({e.as_of for e in examples})
    if len(days) < folds + 1:
        return []
    cut = len(days) // (folds + 1)
    splits = []
    for k in range(1, folds + 1):
        boundary = days[cut * k]
        end = days[min(cut * (k + 1), len(days) - 1)]
        train = [e for e in examples if e.target_date < boundary]
        val = [e for e in examples if boundary <= e.as_of <= end]
        if train and val and len({e.y for e in train}) == 2:
            splits.append((train, val))
    return splits


def select(train: list[Example]) -> tuple[Predictor, dict]:
    """Choose the served predictor on validation data only.

    The test season is never consulted here. Choosing on test and then
    reporting test would quietly turn the headline number into a training
    number.
    """
    splits = rolling_validation(train)
    candidates: dict[str, list[float]] = {"persistence": [], "climatology": []}
    for C in C_GRID:
        candidates[f"logistic_C{C}"] = []

    for tr, val in splits:
        _, yv, _ = _arrays(val)
        Xv, _, av = _arrays(val)
        candidates["persistence"].append(score(yv, fit_persistence(tr).predict(Xv, av))["brier"])
        candidates["climatology"].append(score(yv, fit_climatology(tr).predict(Xv, av))["brier"])
        for C in C_GRID:
            candidates[f"logistic_C{C}"].append(
                score(yv, fit_logistic(tr, C).predict(Xv, av))["brier"]
            )

    mean_brier = {k: round(float(np.mean(v)), 5) for k, v in candidates.items() if v}
    if not mean_brier:
        # Too little history to validate anything: fall back to the baseline
        # rather than an unvalidated model.
        return fit_persistence(train), {"validation_folds": 0, "mean_brier": {}}

    best = min(mean_brier, key=mean_brier.get)
    if best == "persistence":
        chosen = fit_persistence(train)
    elif best == "climatology":
        chosen = fit_climatology(train)
    else:
        chosen = fit_logistic(train, float(best.split("_C", 1)[1]))
    return chosen, {"validation_folds": len(splits), "mean_brier": mean_brier, "selected": best}


def _period(examples: list[Example]) -> dict | None:
    if not examples:
        return None
    return {
        "from": min(e.as_of for e in examples).isoformat(),
        "to": max(e.as_of for e in examples).isoformat(),
        "examples": len(examples),
        "districts": len({e.district for e in examples}),
        "positive_rate": round(sum(e.y for e in examples) / len(examples), 4),
    }


def train_and_evaluate(
    examples: list[Example], horizon_days: int, test_from: date
) -> dict:
    """Train on everything before `test_from`, select on validation folds
    inside that, then evaluate once on the held-out season."""
    train = [e for e in examples if e.target_date < test_from]
    test = [e for e in examples if e.as_of >= test_from]
    if not train or len({e.y for e in train}) < 2:
        raise ValueError("not enough training history with both outcomes to fit anything")

    chosen, selection = select(train)
    baselines = {
        "persistence": fit_persistence(train),
        "climatology": fit_climatology(train),
    }
    # Refit on all history (train + test) for serving is deliberately NOT
    # done: the served coefficients are exactly the ones the test numbers
    # describe. Retraining when a season ends is a new, re-evaluated version.
    test_metrics = {"served": evaluate(chosen, test) if test else None}
    for name, b in baselines.items():
        test_metrics[name] = evaluate(b, test) if test else None

    # The best logistic candidate is scored on test too, even when it was not
    # selected, so "persistence won" can be checked rather than taken on
    # trust. This happens after selection and cannot influence it.
    logistic_scores = {
        k: v for k, v in selection.get("mean_brier", {}).items() if k.startswith("logistic_C")
    }
    if test and logistic_scores:
        best_c = float(min(logistic_scores, key=logistic_scores.get).split("_C", 1)[1])
        test_metrics["logistic"] = evaluate(fit_logistic(train, best_c), test)

    payload = {
        "horizon_days": horizon_days,
        "kind": chosen.kind,
        "features": list(FEATURES),
        "params": chosen.params,
        "baselines": {k: v.params for k, v in baselines.items()},
        "selection": selection,
        "train_period": _period(train),
        "test_period": _period(test),
        "test_metrics": test_metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    digest = hashlib.sha256(
        json.dumps([chosen.kind, chosen.params], sort_keys=True).encode()
    ).hexdigest()[:8]
    payload["version"] = f"dfs-h{horizon_days}-{date.today().isoformat()}-{digest}"
    payload["verdict"] = verdict(payload)
    return payload


def verdict(payload: dict) -> dict:
    """Plain-language summary of whether the served model has skill.

    Brier skill score against persistence: positive means better than simply
    repeating today's state, zero or negative means it is not.
    """
    tm = payload.get("test_metrics") or {}
    served, pers = tm.get("served"), tm.get("persistence")
    if not served or not pers:
        return {"skill_vs_persistence": None, "summary": "no held-out season to evaluate on"}

    def bss(candidate: dict | None, part: str) -> float | None:
        if not candidate:
            return None
        s, b = candidate[part].get("brier"), pers[part].get("brier")
        if s is None or not b:
            return None
        return round(1 - s / b, 4)

    overall, onset = bss(served, "all"), bss(served, "onset")
    logistic = tm.get("logistic")
    if payload["kind"] != "logistic":
        summary = (
            f"The logistic model did not beat {payload['kind']} on validation, "
            f"so {payload['kind']} is served. That is the honest outcome, not a failure to hide."
        )
    elif overall is not None and overall > 0:
        summary = f"Beats persistence on the held-out season (Brier skill {overall:+.1%})."
    else:
        summary = (
            "Selected on validation but does not beat persistence on the held-out "
            "season. Treat its probabilities as no better than today's state."
        )
    return {
        "skill_vs_persistence": overall,
        "onset_skill_vs_persistence": onset,
        "logistic_test_skill_vs_persistence": bss(logistic, "all"),
        "logistic_test_onset_auc": logistic["onset"].get("roc_auc") if logistic else None,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def save(payload: dict, path: Path | None = None) -> Path:
    path = path or artifact_path(payload["horizon_days"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load(horizon_days: int, path: Path | None = None) -> dict | None:
    path = path or artifact_path(horizon_days)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def predictor_from(payload: dict) -> Predictor:
    if payload["features"] != list(FEATURES):
        # Coefficients silently applied to reordered features would produce
        # confident nonsense. Refuse instead.
        raise ValueError(
            "artifact features do not match the code's FEATURES; retrain the model"
        )
    return Predictor(payload["kind"], payload["params"])


def predict_one(payload: dict, features: dict[str, float]) -> float:
    predictor = predictor_from(payload)
    X = np.asarray([[features[name] for name in FEATURES]], dtype=float)
    a = np.asarray([int(features["affected"])])
    p = float(predictor.predict(X, a)[0])
    return p if math.isfinite(p) else 0.5
