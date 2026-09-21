# 0014 — Rainfall Input

**Status:** BUILT, collected daily, **not yet served**. 22 Sep 2026.

Rainfall was the model's largest missing input (`0010`): without it a flood is
visible to the model only once a district has already been reported as
affected. This adds daily rainfall per district. The model that uses it was
trained, tested, and **not deployed**, because it did not win on the data the
selection rules choose with. The record below is why, and what would change
that.

## Source

Re-checked 21 Sep 2026, against each source's own `robots.txt`:

| Source | Result |
|---|---|
| Open-Meteo (`api.`, `archive-api.`) | `Disallow: /` — unchanged since `0010` |
| NASA POWER | `Disallow: /api/`, and names AI clients explicitly |
| India-WRIS | No response from this network |
| Copernicus ERA5 (CDS) | Allowed with a free account, but about 5 days behind: usable for training, useless for tomorrow |
| **NASA GPM IMERG (GES DISC)** | **Chosen.** No rule for general clients (it blocks named crawlers and explicitly allows direct user tools); free Earthdata account |

**Product:** IMERG Late Run V07 daily (`GPM_3IMERGDL`). Early is less
corrected; Final is 3 months behind. Late is the only one both good enough to
train on and current enough to use — and training on Final while serving Late
would mean learning from numbers the model never sees live.

**Verified against the live archive** (`python -m app.services.weather.check`):
units are `mm/day`, the array is `[time][lon][lat]`, and on 1 June 2025 — the
Barak Valley flood — Hailakandi, Karimganj and Cachar are among the four
wettest districts in Assam (32–47 mm), with 31 May at 90–97 mm. Every request
checks that the grid cells returned are the ones asked for, from the
coordinates the server labels each row with.

## Design

- **Per district:** the mean of the 0.1° cells in a box the size of the
  district's own bounding box (35 boxes from OSM via Overpass, committed as
  `geo/rainfall/assam_district_points.json`). One OPeNDAP request per day
  covers all of Assam — a few kilobytes, not a 25 MB global file.
- **Stored** in `hazard_observations` as hazard type `rainfall`, with no
  geometry, so no spatial query (damage matching, scenarios, corroboration)
  can pick it up. Same run log, catch-up and idempotency as the reports.
- **Missing is never dry.** A cell with the fill value is skipped; a district
  with no valid cells is not written; a rain window with any unmeasured day
  produces no rain features at all.
- **Lagged one day.** Day D's file is posted about 20:00 IST on D+1; report D
  is scored at 07:30 on D+1. So a report dated D is trained and scored with
  rain up to D−1 — the model is never trained on rain it could not have had.
- **Artifacts name their own inputs.** A model file lists its features in
  coefficient order; the code refuses only features it cannot compute. The
  deployed pre-rainfall artifacts load unchanged.
- **Fallback, labelled.** If a model needs rain that has not arrived, that row
  is served by the artifact's persistence baseline, stored as
  `persistence_fallback`, and the explanation says why.

## Result

Backfilled 24 Apr 2025 – 20 Sep 2026 (515 days × 35 districts). Both feature
sets trained on identical rows; train = 2025 season, test = 2026 season.

Descriptively, rain carries signal: a district not affected today became
affected the next day 18% of the time after more than 100 mm over three days,
against 2% otherwise.

| 1-day | Validation Brier (2025 folds) | Test Brier (2026) | Test onset AUC |
|---|---|---|---|
| Persistence | 0.02191 | 0.0402 | 0.500 |
| Reports only (served) | **0.02164** | 0.0402 | 0.706 |
| Reports + rainfall | 0.02261 | **0.0388** | **0.756** |

| 3-day | Validation Brier | Test Brier | Test onset AUC |
|---|---|---|---|
| Persistence (served) | **0.04157** | 0.0693 | 0.500 |
| Reports only, logistic | 0.04208 | 0.0660 | 0.669 |
| Reports + rainfall, logistic | 0.04374 | **0.0637** | **0.681** |

**On the held-out season, rainfall is better at both horizons. On validation,
it is worse.** The selection rule chooses on validation, so reports-only was
chosen and nothing deployed changed.

Why the two disagree: validation is forward-chaining inside one season, and
its first fold trains on six weeks (May to mid-June, 1,428 rows). Three extra
inputs fitted on six weeks do not generalise; fitted on a whole season, as for
the test, they do.

## Why the rule was not changed

Changing the selection procedure after seeing that rain wins on test would
make the test season part of the choice — the same mistake the selection code
is written to prevent (`district_model.select`). The 2026 test numbers are
now known, so they cannot be used to justify rain either.

**What would:** forecasts on days no version of the model has seen. The next
step is a shadow run — the rainfall model scored every day alongside the
served one, stored, and graded live against the same outcomes. If it beats
the served model there, that is evidence the choice did not produce.

## What was built

- `app/services/weather/` — `imerg.py` (client, parsing, alignment check),
  `points.py` (district boxes and name aliases), `ingest.py`, `check.py`
- `geo/rainfall/fetch_district_points.py`, `assam_district_points.json`
- `dataset.py` — `RAIN_FEATURES`, `RAIN_LAG_DAYS`, `rain_features`;
  `SPELLING_FIXES` for "D hemaji" (one 2025-10-06 row whose first letter never
  reached the PDF's text layer, which had created a phantom 36th district)
- `district_model.py` — artifacts carry their own feature list;
  `for_inputs` fallback
- `train.py` — trains both feature sets on identical rows, chooses on
  validation, prints both on test marked as not used for choosing
- Daily job: a rainfall step before scoring, independent of the ASDMA portal
- Readiness: `data_freshness` now counts only the flood report feed (it had
  counted any source's runs, so a fresh rainfall day would have hidden a dead
  report feed); new `rainfall_freshness` and `rainfall_points` checks
- The points file is exempted from the `geo/**/*.json` ignore rule and copied
  into both images; a test enforces both

## Operating it

`EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` in the user environment of the
machine that runs the daily job (see `scripts/scheduling/README.md`). The
scheduled task loads them itself. Without them the rainfall step fails, and
scoring carries on unaffected — the served model does not use rain.
