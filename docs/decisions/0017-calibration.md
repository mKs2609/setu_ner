# 0017 — Calibration: Does 12% Mean 12%?

**Status:** MEASURED from 29 Sep 2026, on the served artifacts, without
retraining them.

## Why

The model page reported Brier and AUC. Between them they answer two
questions:

- **Brier** — are the numbers close, on average?
- **AUC** — are the risky days ranked above the quiet ones?

Neither answers the one an operator acts on. If this says 12% on a hundred
district-days, does it happen on about twelve of them? A model can score well
on both measures above and still be reliably overconfident, and this product
puts a probability in front of a person and invites them to route a truck
with it.

So calibration was the missing leg. Everything else in the evaluation was
rigorous; this was simply never asked.

## What is measured

`district_model.calibration()` sorts forecasts into bands by what they
predicted, and for each band reports what was predicted against what
happened. It also returns Murphy's decomposition of the Brier score:

    brier ~= reliability - resolution + uncertainty

| | |
|---|---|
| **reliability** | how far the bands sit off the diagonal. Lower is better; 0 is perfect |
| **resolution** | how far the bands separate from the base rate. Higher is better |
| **uncertainty** | `o(1-o)`, how hard the problem is. Nothing to do with the model |

The identity is exact for the *binned* forecasts, so only approximate for the
continuous ones underneath. The returned `residual` reports that gap rather
than asking anyone to assume it is small; on real data it is +0.0003 at one
day and +0.000000 at three.

Bands are not uniform. Nine district-days in ten are quiet and predicted
under 5%, so ten equal bins would put almost everything in the first one and
say nothing. The edges are fine where the predictions live and coarse where
they are sparse.

## What it found

**One day (logistic, served).** Reliability **0.00065** — well calibrated
overall. But the middle bands lean one way:

| band | n | said | happened |
|---|---|---|---|
| 0.00–0.01 | 840 | 0.7% | 1.0% |
| 0.02–0.05 | 1,574 | 3.2% | **2.6%** |
| 0.20–0.35 | 49 | 27.3% | **44.9%** |
| 0.50–0.75 | 169 | 64.9% | 72.8% |
| 0.75–1.00 | 307 | 87.8% | 89.6% |

It **understates risk in the middle** — when it says 20–35%, the rate is
closer to 45% — and runs **slightly hot on quiet days**, saying 3.2% where
2.6% happened.

That second line is a candidate explanation for something that had none. The
live track record has been negative through a quiet post-monsoon stretch, and
persistence gives an unaffected district 1.9%. A model saying 3.2% where the
truth is nearer 2.6% loses to that on exactly the sort of day the corridor
has had for weeks. Neither confirmed nor assumed here — written down so the
November retrain has something specific to test.

**Three days (persistence, served).** Only two bands are populated, because
persistence emits exactly two numbers. Reliability **0.00438**, nearly seven
times worse than the logistic model's, and the reason is one row:

| band | n | said | happened |
|---|---|---|---|
| 0.35–0.50 | 528 | 48.2% | **67.2%** |

Persistence substantially understates the chance a flooded district is still
flooded three days later. It is still what `0010` says should be served,
because it won on validation — but this is the first concrete account of what
that choice costs.

## What it does not do

**It does not retrain.** The obvious home for this is `evaluate()`, which
already walks the held-out season — but then the numbers would only appear by
retraining, and the retrain procedure is fixed until after the season
(`docs/retraining.md`). Calibration is a question about the model that is
*already serving*, so it is asked of that model separately.
`services/model/calibrate.py` loads the artifact, reads the test window out
of the artifact itself, rebuilds those district-days and predicts. No
coefficient moves, no version changes.

**It does not choose the window.** Taking the period from the artifact means
the calibration describes the same forecasts the published Brier and AUC
describe, rather than a window picked afterwards that happens to look better.

**It does not pretend the rows are identical.** Rebuilding from history as it
stands today gives 4,454 rows against the 4,585 recorded at training, because
the report record has been repaired since — a district name broken by the PDF
text layer, population reparsed. The difference is reported in the payload and
on the page instead of being smoothed over.

## The live curve is withheld

311 graded forecasts with 7 positives cannot support a reliability curve;
spread over nine bands it is a picture of noise. The API refuses to draw one
below **500 pairs and 20 positives**, and says so with the counts. The
threshold is written down in `routers/model.py` rather than judged case by
case later, for the same reason the shadow test's rule is (`0015`).

## Where it shows

`GET /api/v1/model/status` gains a `calibration` block per horizon, plus
`calibration` inside each live track record entry. The accessibility page
draws a reliability diagram — server-rendered SVG, no client JavaScript, dot
area proportional to the number of forecasts in the band, with the gap to the
diagonal drawn as a line so the error is visible rather than inferred.
