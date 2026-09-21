"""
Why the model gave a district the probability it did.

EXACT, NOT APPROXIMATE
`0001` Tier 2 item 8 asked for explanations "on top of SHAP/feature
importance". For a linear model that is unnecessary: logistic regression's
log-odds are literally a sum, so each feature's contribution is

    coef_i x (x_i - mean_i) / scale_i

measured against a district with every feature at its training average. The
contributions plus that average's log-odds reproduce the prediction exactly
(a test asserts it). This is what SHAP converges to for a linear model with
independent features, computed directly, with no sampling and no library.

Persistence has no features to attribute: it is one rule, and the explanation
says which branch of the rule applied and how often that branch came true in
training.

PLAIN LANGUAGE, FROM TEMPLATES
Each sentence is produced from a template filled with the district's actual
values -- "12 districts are affected statewide today". Nothing is generated
freely, so every clause is traceable to a number in the response, and the
same inputs always yield the same words.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.model import district_model as dm

# How to say each feature's actual value, and what raising it means.
# `value` receives the raw feature dict and returns a human phrase.
PHRASES = {
    "affected": lambda f: (
        "the district is listed as flood-affected today"
        if f["affected"] else "the district is not listed as affected today"
    ),
    "log_population": lambda f: (
        f"{int(round(math.expm1(f['log_population']))):,} people are reported affected"
        if f["log_population"] > 0 else "no affected population is reported"
    ),
    "affected_frac_7d": lambda f: (
        f"it was listed on {round(f['affected_frac_7d'] * 100)}% of report days in the last week"
    ),
    "run_length": lambda f: (
        f"it has been listed {round(f['run_length'] * 14)} report day(s) in a row"
        + (" (14 or more)" if f["run_length"] >= 1 else "")
    ),
    "population_trend": lambda f: (
        "the affected population is rising since the previous report"
        if f["population_trend"] > 0.01
        else "the affected population is falling since the previous report"
        if f["population_trend"] < -0.01
        else "the affected population is unchanged since the previous report"
    ),
    "relief_camps_open": lambda f: (
        "relief camps are open" if f["relief_camps_open"] else "no relief camps are open"
    ),
    "infra_damage_7d": lambda f: (
        "road, bridge or embankment damage was reported in the last week"
        if f["infra_damage_7d"] else "no infrastructure damage was reported in the last week"
    ),
    "affected_frac_60d": lambda f: (
        f"over the previous 60 days it was listed on {round(f['affected_frac_60d'] * 100)}% of report days"
    ),
    "state_log_affected": lambda f: (
        f"{int(round(math.expm1(f['state_log_affected'])))} district(s) are affected statewide today"
    ),
    "state_trend": lambda f: (
        "the number of affected districts statewide is growing"
        if f["state_trend"] > 0.01
        else "the number of affected districts statewide is shrinking"
        if f["state_trend"] < -0.01
        else "the number of affected districts statewide is unchanged"
    ),
    # Rain is lagged a day (dataset.RAIN_LAG_DAYS), so the phrases say
    # "up to yesterday" rather than implying today's rain is known.
    "rain_1d": lambda f: (
        f"{math.expm1(f['rain_1d']):.0f} mm of rain fell on the latest day measured"
    ),
    "rain_3d": lambda f: (
        f"{math.expm1(f['rain_3d']):.0f} mm of rain fell over the 3 days measured up to yesterday"
    ),
    "rain_7d": lambda f: (
        f"{math.expm1(f['rain_7d']):.0f} mm of rain fell over the 7 days measured up to yesterday"
    ),
}


@dataclass
class Contribution:
    feature: str
    value: float
    log_odds: float
    sentence: str


def _logit(p: float) -> float:
    p = min(max(p, dm.EPS), 1 - dm.EPS)
    return math.log(p / (1 - p))


def explain(payload: dict, features: dict[str, float], district: str) -> dict:
    """Explanation of one forecast from one artifact.

    `features` are the raw values from dataset.features_for for the as-of
    day; `payload` is the artifact that produced the forecast.
    """
    payload = dm.for_inputs(payload, features)
    probability = dm.predict_one(payload, features)
    horizon = payload["horizon_days"]
    kind = payload["kind"]
    base = {
        "district": district,
        "horizon_days": horizon,
        "model_kind": kind,
        "model_version": payload["version"],
        "probability": round(probability, 5),
    }
    if "fallback_reason" in payload:
        base["fallback_reason"] = payload["fallback_reason"]

    if kind == "persistence":
        p = payload["params"]
        affected = bool(features["affected"])
        rate = p["p_given_affected"] if affected else p["p_given_not_affected"]
        branch = "affected" if affected else "not affected"
        return {
            **base,
            "method": "rule",
            "headline": (
                f"{district} is {branch} today, and in training a district that was {branch} "
                f"was affected {horizon} day(s) later {rate:.0%} of the time."
            ),
            "contributions": [],
            "why_this_model": (
                payload["fallback_reason"].capitalize() + ". It uses only today's state, so "
                "it cannot anticipate a flood that has not yet been reported."
                if "fallback_reason" in payload
                else "Persistence is served at this horizon because the logistic model did not "
                "beat it on validation. It uses only today's state, so it cannot anticipate "
                "a flood that has not yet been reported."
            ),
        }

    if kind != "logistic":
        return {**base, "method": "none", "headline": f"No explanation available for {kind}.",
                "contributions": []}

    params = payload["params"]
    mean, scale, coef = params["scaler_mean"], params["scaler_scale"], params["coef"]
    contributions = []
    # In the artifact's own order: its coefficients are indexed that way.
    for i, name in enumerate(payload["features"]):
        z = (features[name] - mean[i]) / scale[i]
        contributions.append(
            Contribution(name, features[name], coef[i] * z, PHRASES[name](features))
        )

    # Log-odds of a district with every feature at its training average.
    average_log_odds = params["intercept"]
    total = average_log_odds + sum(c.log_odds for c in contributions)
    reconstructed = 1 / (1 + math.exp(-total))

    ranked = sorted(contributions, key=lambda c: -abs(c.log_odds))
    raising = [c for c in ranked if c.log_odds > 0.05][:3]
    lowering = [c for c in ranked if c.log_odds < -0.05][:3]

    parts = [f"{probability:.0%} chance {district} is listed as affected in {horizon} day(s)."]
    if raising:
        parts.append("Raising it most: " + "; ".join(c.sentence for c in raising) + ".")
    if lowering:
        parts.append("Lowering it most: " + "; ".join(c.sentence for c in lowering) + ".")

    return {
        **base,
        "method": "exact_linear_attribution",
        "headline": " ".join(parts),
        "average_district_probability": round(1 / (1 + math.exp(-average_log_odds)), 5),
        "contributions": [
            {
                "feature": c.feature,
                "value": round(c.value, 4),
                "log_odds": round(c.log_odds, 4),
                "direction": "raises" if c.log_odds > 0 else "lowers" if c.log_odds < 0 else "none",
                "sentence": c.sentence,
            }
            for c in ranked
        ],
        "check": {
            "reconstructed_probability": round(reconstructed, 5),
            "matches_prediction": abs(reconstructed - probability) < 1e-3,
        },
        "how_to_read": (
            "Each contribution is in log-odds, relative to a district with every input at its "
            "training-season average. They add up exactly to the prediction. A large "
            "contribution means the input is far from average and the model weights it heavily; "
            "it does not mean the input causes flooding."
        ),
    }
