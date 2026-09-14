# 0012 — Explanations and the Audit Trail (Phase 6)

**Status:** BUILT. Every forecast, every road's accessibility and every supply
plan can now say why it is what it is, in plain sentences tied to the numbers.
Plans can be saved as immutable records, and operators can log what they did
instead. 15 Sep 2026.

`0001` §7 Tier 2 item 8 asked for plain-language explanations "on top of
SHAP/feature importance", and its pipeline ends in "EXPLANATION + AUDIT TRAIL
(+ plain-language generation, + override feedback log)". This is that stage.

## Principle: an explanation must not be able to disagree with its number

The failure to avoid is an explanation that reads well and is subtly wrong —
a story generated after the fact that does not actually reproduce the value
on screen. Three rules follow:

1. **Explanations are computed from the same artifacts and figures as the
   output**, never recomputed separately.
2. **Sentences come from templates filled with actual values.** No free text
   generation, no language model. The same inputs always give the same
   words, and every clause maps to a number.
3. **Where arithmetic can be checked, it is** — and the check is shown, not
   hidden.

## Forecasts: exact attribution, no SHAP library needed

The 1-day model is logistic regression, whose log-odds are a sum. Each
input's contribution is `coef × (value − training mean) / training scale`,
relative to a district with every input at its training average. The
contributions plus that average's log-odds **reproduce the prediction
exactly** — a test asserts it on random coefficients, and every explanation
carries a `matches_prediction` check. This is what SHAP converges to for a
linear model, computed directly with no sampling.

For 5 June 2025, Cachar, tomorrow:

> 96% chance Cachar is listed as affected in 1 day. Raising it most: the
> district is listed as flood-affected today; 19 districts are affected
> statewide today; 80,028 people are reported affected. Lowering it most: it
> has been listed 5 report days in a row; road, bridge or embankment damage
> was reported in the last week.

Two things the explanation says about itself:
- **It is not causal.** "A large contribution means the input is far from
  average and the model weights it heavily; it does not mean the input causes
  flooding." "Damage reported lowers the chance" is what the model learned
  from how reports evolve, not a claim about hydrology.
- **Persistence is explained as the rule it is**: "Cachar is affected today,
  and in training a district that was affected was affected 3 days later 48%
  of the time." — along with why persistence, not the logistic model, is
  served at that horizon.

`GET /api/v1/model/explain/{district}?as_of=`

## Roads: two halves, two levels of trust

`current_accessibility = 1 − P(district affected tomorrow) × terrain exposure`,
so the explanation has exactly two parts and labels them differently:

> Accessibility 0.979 = 1 − 0.023 (chance Cachar is flood-affected tomorrow)
> × 0.89 (this road's terrain exposure). It sits 11 m above Cachar's low
> ground, so it takes 89% of the district risk.

The district half is an **evaluated forecast** (with its own feature-level
explanation); the terrain half is a **stated prior, not fitted**. The 2025
baseline is compared, with a reminder that it describes a whole season while
the forecast describes tomorrow.

If the model has been retrained since the road was scored, the explanation
would describe a different model than the stored value — so it checks, and
says so (`explains_stored_value`, `model_mismatch_note`).

`GET /api/v1/accessibility/{road_id}/explanation` — and on the map, clicking a
road opens it.

## Plans: a narrative with evidence

`POST /logistics/plan` now returns an `explanation` in five sections —
**Situation, What the plan does, Route choices, What limits it, Left out** —
where every statement carries an `evidence` object repeating the figures it
was built from. In the UI each sentence expands to show them.

It computes nothing new: the limits are the optimiser's own dual-value
sentences repeated verbatim, route trade-offs are read from the two route
summaries ("Haflong → Udharbond takes the lower-exposure route: +54 min for
13.7 fewer exposure-km (32 → 11 bridges)"), and "Left out" is assembled from
the plan's unreachable circles, off-graph people, unattributed district
totals and omitted solver residue. An explanation that did its own arithmetic
could contradict the plan; this one cannot.

## The audit trail

**Saving is opt-in** (`"save": true`). A saved recommendation freezes:
the request, the full result, the explanation, the report day the demand came
from, whether it was a replay or used example stock, and the versions of both
model artifacts and the gazetteer. It is **never updated** — there is no PUT,
PATCH or DELETE, and a test asserts those return 405.

**Overrides are append-only.** An operator who deviates records the action
(accepted / modified / rejected), an optional target run, a reason category
and a **required** reason:

| Category | Signal it carries |
|---|---|
| road_condition_differs | the forecast was wrong about a road |
| stock_figure_wrong | the depot inputs were stale |
| fleet_unavailable | trucks or drivers were not there |
| demand_differs | the report did not match the ground |
| priority_judgement | the operator chose a different trade-off |
| other | — |

This is `0001` §5's "log every override with reason". Categorised, it becomes
the most direct evidence the system will ever get about which assumption
failed — in particular, `road_condition_differs` against a saved route is the
first route-level ground truth this project could accumulate for fitting the
terrain prior.

Operator ids are opaque and device-scoped, like reporter ids (`0005`): no
names, no phone numbers. Saves are limited to 60 an hour overall and
overrides to 30 an hour per operator — not security, since nothing here is
authenticated, but enough to stop a retry loop filling the tables.

Pages: `/recommendations` (list, with coverage and override counts) and
`/recommendations/{id}` (frozen record, explanation, versions, override form).

## Known limitations

- **No authentication.** Anyone who can reach the API can save a plan or
  record an override, as with field reports. Deployment needs auth in front
  of the write endpoints before real operators use it.
- **Overrides are not yet fed back.** They are captured and categorised; using
  them to recalibrate the terrain prior or flag depots is future work, and
  needs volume first.
- **Explanations describe the model, not the world.** A feature that "raises"
  a probability is one the model weights, which is not the same as a cause.

## What was built

- `services/explain/` — `forecast.py` (exact attribution + rule explanation),
  `road.py`, `plan.py` (narrative with evidence), `audit.py`
- `routers/recommendations.py` (replacing the stub), explanation endpoints on
  `model` and `accessibility`, `save`/`label` on `logistics/plan`
- `infra/migrations/0003_recommendations_audit.sql`
- Web: "Why?" per district with contribution bars; click-a-road explanation;
  "Why this plan" with expandable evidence; save-as-record on logistics;
  `/recommendations` and `/recommendations/{id}` with the override form

## Testing

21 new tests. Attribution reconstructs the prediction on five random
coefficient sets; sentences state the actual values; the narrative uses the
plan's figures, carries evidence on every statement, repeats limits
verbatim and never omits what the plan left out; records cannot be edited or
deleted; overrides need a reason and a known action and category; saving an
override leaves the record's outputs byte-identical; an unsaved plan leaves no
row. Verified in the browser end to end: plan → save → open record → override.

## Next

Deployment — covered separately. The remaining unbuilt item from the original
phases is Sentinel-1 flood extent (`0009`), which needs a Copernicus account
and a SAR pipeline.
