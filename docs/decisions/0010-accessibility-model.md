# 0010 — The Accessibility Model (Phase 3)

**Status:** BUILT, and honest about what won. `current_accessibility` is
populated for the first time: 71,520 corridor roads, every value carrying a
model version and an as-of date. 13 Sep 2026.

## What unblocked it

`0007` stopped Phase 3 at **3 labelled road-days**. Two findings changed that.

**1. The archive goes back further than we were using.** DRIMS serves
reports from **1 May 2025** onward (2024 and earlier return nothing). A
polite backfill brought history from 34 days to **312 published report
days** across two monsoons — 179 for 2025, 136 for 2026 to 12 Sep. Three
downloads were refused by the existing date check because the portal served
a different day than was asked for; they stay recorded as failed, not
filed under the wrong date.

**2. The right target is statewide flood state, not road damage.** Two
reasons, both found in the data:

| | |
|---|---|
| Too few | Geolocated damage inside the corridor: 23 matched reports, even after the backfill |
| Dated wrongly | DRIMS damage rows carry the date they were **reported**. One Cachar row records rain on 20 July that reached the report on 12 August. Forecasting that forecasts paperwork. |

What the report publishes promptly, every day, for every district in Assam,
is **whether the district is flood-affected**. So the model predicts
`affected(district, day + h)` for h = 1 and 3 days. Trained statewide, that
is **6,612 training examples** instead of three.

A district is labelled *not affected* only when a report was published that
day and the district is absent from it. A day with no report is **unknown**,
never quiet — otherwise the model would learn that floods end whenever the
portal is down.

## A bug the model found in ingestion

Building the district list surfaced `"Cacha r"`, `"Hailakand i"`,
`"Sribhu mi"` and `"Dima- Hasao"` as separate districts. The PDF wraps
table cells mid-word, and `normalise_district` only collapsed whitespace, so
**75 corridor rows had been stored with `district = NULL`** — invisible to
corroboration (`0006`) and current-conditions routing (`0007`), and, for the
model, a flooded Cachar day would have counted as a dry one.

Fixed at the source: names are also compared letters-only against the
known aliases, which repairs exactly this and still maps an unknown district
to `None`. `python -m app.services.ingestion.renormalise_districts` repaired
the stored rows from `place_name` (safe: `observation_key` does not include
the district). Any database restored from an older dump needs it run once.

## The bar: persistence

Flood state is sticky. A district affected today is affected tomorrow about
74% of the time; one that is not, about 2%. So "accurate" means nothing
alone — repeating today's state already scores well. Everything is reported
against two baselines:

- **climatology** — the training base rate, same for everyone
- **persistence** — P(affected tomorrow | affected today), two numbers

The served predictor is chosen on **forward-chaining validation folds inside
the 2025 season** (always train on the past, validate on what followed;
shuffled k-fold would leak tomorrow into yesterday). The 2026 season is
held out and evaluated once.

## Results

Trained 1 May – 30 Oct 2025; tested 1 May – 11 Sep 2026 (4,550 district-days
for h=1). Brier score, lower is better.

| 1-day | All: Brier | All: AUC | Onset: Brier | Onset: AUC |
|---|---|---|---|---|
| Persistence (**served**) | **0.0397** | 0.895 | 0.0241 | 0.500 |
| Logistic regression | 0.0401 | **0.935** | **0.0238** | **0.717** |
| Climatology | 0.1056 | 0.500 | 0.0261 | 0.500 |

| 3-day | All: Brier | All: AUC | Onset: Brier | Onset: AUC |
|---|---|---|---|---|
| Persistence (**served**) | 0.0682 | 0.810 | 0.0432 | 0.500 |
| Logistic regression | **0.0662** | **0.872** | **0.0425** | **0.679** |
| Climatology | 0.1071 | 0.500 | 0.0439 | 0.500 |

### What that means

- **Persistence won validation at both horizons, so persistence is served.**
  Logistic regression was slightly worse on every 2025 fold (e.g. 0.0222 vs
  0.0216 at h=1).
- **On the held-out season, logistic ties at 1 day and edges ahead at 3 days**
  (Brier skill +2.9%). It was **not** switched in after seeing that — choosing
  the model on the test season and then reporting the test season would turn
  the headline number into a training number. The next retrain, with 2026 in
  the training data, decides that fairly.
- **The real signal is onset ranking.** Persistence cannot see a flood coming
  by construction (AUC 0.50). Logistic ranks tomorrow's new floods at AUC 0.72
  — after today's state, its largest coefficients are statewide spread
  (+0.53, standardised) and 60-day district flood-proneness (+0.29). That is real,
  modest skill, and it is the part a rainfall input would most improve.
- Base rates shifted between seasons (7.0% → 11.7% affected). Calibration
  under that shift is why Brier is close even where ranking is clearly better.

## Per-road accessibility

```
current_accessibility = 1 − P(district affected tomorrow) × terrain exposure
exposure = clamp(1 − height_above_district_floor / 100 m, 0.1, 1)
floor    = the district's 10th-percentile road elevation (from 0009)
```

The two halves deserve different trust, and the API returns them separately
(`/api/v1/accessibility/{id}` → `components`):

- **The district probability is measured** — the tables above.
- **The exposure is a prior, not fitted.** The 100 m and the 0.1 floor are
  judgement, stated in `score.py` rather than buried. `confidence` is
  recorded as `low` for this reason.

What it does on a flood day, with persistence served: a valley road in a
flooded Cachar scores **1 − 0.743 × 1.0 = 0.26**; a Dima Hasao ridge road in
a flooded Dima Hasao scores **1 − 0.743 × 0.1 = 0.93**. On 12 Sep no corridor
district is listed, so every road sits at 0.98 or above — which is correct,
not a flat map.

**Sanity check on the prior.** Damage matching (below) found 23 corridor
damage reports within 300 m of a road. Their mean exposure is **0.957**
against **0.88** for all scored roads: the direction the prior predicts, but
23 reports, all on the valley floor, is a sanity check, not validation. Eight
of the 23 are bridges, far above their share of the network — a feature
worth adding once there are enough reports to fit anything.

## Damage matching

`0004` stored damage coordinates and left the join to the road graph undone.
`app/services/model/damage_matching.py` does it with explicit quality:
≤100 m `confident` (18), ≤300 m `approximate` (5), otherwise `none` with no
road (257 — mostly elsewhere in Assam). Nothing is snapped to "whatever is
closest".

## Safety of what is written

- **Never without provenance.** `current_accessibility` is written only by
  the scoring job, together with `accessibility_model_version` and
  `current_accessibility_as_of`. A test asserts no orphan values exist.
- **Never stale.** Scoring refuses a report more than 3 days old and exits
  non-zero; the API recomputes staleness at read time.
- **Never borrowed.** The Meghalaya roads have no Assam report, so they stay
  NULL (38,740 unscored roads) rather than inheriting a neighbour's number.
- **Field reports still never write it** — the test now checks a submission
  leaves the value, version and date untouched.
- **The artifact is JSON, not a pickle.** Loading it cannot execute code, the
  coefficients are reviewable, and the API serves it with numpy alone. It
  refuses to load if its feature order differs from the code's.
- **It grades itself.** Every live forecast is stored
  (`district_flood_forecasts`); once its target day's report arrives,
  `/api/v1/model/status` scores it against persistence.

## Rainfall: tried, blocked, recorded

Rainfall is the model's biggest missing input — without it a flood is only
visible once reported. Every free daily source was checked and respected:

| Source | Result |
|---|---|
| NASA POWER | `robots.txt` disallows `/api/` |
| Open-Meteo forecast / archive | `robots.txt` disallows `/` |
| CHIRPS | `robots.txt` disallows `/` |
| Nominatim (for district centroids) | disallows `/search` |

The routes that remain are a Copernicus CDS account (ERA5) or an IMD data
request — both a registration decision for the team, not code.

## What was built

- `app/services/model/` — `dataset.py` (pure label and feature rules),
  `district_model.py` (fit, select, evaluate, JSON artifacts), `history.py`,
  `train.py`, `score.py`, `damage_matching.py`
- `routers/model.py` — `/model/status`, `/model/districts`
- `/accessibility/{id}` now separates model from baseline; roads GeoJSON
  carries the forecast and its date
- `infra/migrations/0002_accessibility_model.sql`
- `ml/models/district_flood_state_h{1,3}.json`
- Web: the stub `/accessibility` page is now the model screen — forecasts
  with their persistence reference, the test tables, caveats, and a map that
  switches between baseline and forecast
- The daily scheduled run now matches damage and re-scores after ingesting
- Web layout sets an explicit light background; in a dark-mode browser every
  page had been drawing grey text on black

## Testing

30 new tests, 175 in the suite, none skipped with the database. Most target
failures that would not crash: an unpublished day becoming a negative label,
features peeking past the as-of day, validation splits leaking the future,
selection seeing the test season, coefficients applied to reordered features,
a far-away damage point being snapped, a stale report scored as current.

## Next

- **Retrain after the 2026 season closes** (October) with both seasons in
  training; that is where logistic's onset skill gets a fair chance to be
  selected.
- **Rainfall**, via a registered source — the single change most likely to
  move onset skill.
- Fit the exposure prior once geolocated damage reaches a few hundred reports,
  with bridges as a feature.
- Phase 4 (demand and logistics) can now consume `predicted_accessibility`.
