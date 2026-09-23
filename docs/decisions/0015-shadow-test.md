# 0015 — Shadow Test for the Rainfall Model

**Status:** RUNNING from reports dated 22 Sep 2026. Rule fixed the same day,
before any graded forecast existed.

## Why

The rainfall model beat the served model on the 2026 test season and lost on
the 2025 validation folds (`0014`). The selection rule chooses on validation,
so it was not served — and the rule was not changed after seeing the test,
because that would make the test season part of the choice. The 2026 numbers
are spent. Only days that neither model has seen can settle it.

## What runs

Two frozen challenger artifacts,
`ml/models/district_flood_state_h{1,3}_challenger.json`:

| | 1-day | 3-day |
|---|---|---|
| Version | `dfs-h1-shadow-2026-09-22-11d3420a` | `dfs-h3-shadow-2026-09-22-d78f8d3b` |
| Model | logistic, report features + `rain_1d`, `rain_3d`, `rain_7d` | same |
| C (chosen on 2025 validation among logistic candidates) | 0.1 | 0.01 |
| Trained on | 2025 season, as the served model | same |

The challenger is the logistic model even at 3 days, where validation
preferred persistence: being tested is its purpose. Its C still came from
validation, so no test number entered the fit.

Every morning the scorer runs it after the served model and stores its
forecasts in `district_flood_forecasts` with `model_kind = 'shadow_logistic'`.
It never touches roads, the map, explanations or the served track record —
every reader of that table selects `served_only()`, and a test plants a 99.9%
shadow forecast in the real database and checks no endpoint returns it (the
test fails if the filter is removed). A row the challenger could not score
because rain had not arrived is **not stored**: it would be persistence under
the challenger's name.

## The rule

Stored in each challenger artifact as `promotion_rule`, and applied per
horizon to pairs (same district, report day, horizon; both forecasts stored;
outcome published; report dated on or after `frozen_on`):

1. Nothing is decided before **1,500 pairs** and **30 flood onsets** — pairs
   where the district was not affected on the report day and was on the
   target day. Quiet days do not count toward the 30.
2. Then the 90% interval of mean Brier(served) − Brier(challenger), from 2,000
   bootstrap resamples of **whole report days** (seed 0). Days, not rows:
   districts on one day share its weather, so treating them as independent
   would make the interval too narrow.
   - entirely above 0 → **promote**
   - entirely below 0 → **reject**
   - otherwise → **undecided**, keep collecting

The verdict is published at `/api/v1/model/status` → `shadow_test` and on the
model page. **Nothing is promoted automatically**: a promote verdict is
evidence for a deliberate change, recorded here.

Changing the model, the freeze date or the rule means freezing a new
challenger (`--freeze-challenger --replace-challenger`), which restarts the
count from zero. The command refuses without the second flag.

## How long it will take

Roughly 34 districts × one report a day, so ~1,500 pairs in about seven weeks
of published reports. Thirty flood onsets is the binding constraint: the 2026
test season (May–September) had 99 at one day. The rest of the 2026 season may
not reach 30; the verdict most likely arrives during the 2027 monsoon.

## What was built

- `app/services/model/shadow.py` — challenger freezing, `served_only()` /
  `shadow_only()`, pairing, the rule, the day-block bootstrap, `track_record`
- `score.py` — challengers scored after the served model; fallback rows dropped
- `train.py --freeze-challenger [--replace-challenger]`
- `routers/model.py` — `shadow_test` in the status; the district list and
  track record filtered to served rows; `routers/accessibility.py` likewise
- Web: a shadow-test section on the model page, showing progress to the minimums
- `tests/test_shadow.py`
