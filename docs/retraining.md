# Retraining the forecast model

**When:** after the monsoon ends, once no new flood days are arriving —
around November. Not mid-season: a model swapped in halfway makes the live
track record a mixture of two models, and neither can be judged.

This procedure is written *before* the retrain so the rules cannot be bent
once the numbers are on screen. It is the same discipline as
`docs/decisions/0015`.

## What changes, and the problem it creates

Today's artifacts are trained on the 2025 season and tested once on 2026.
After the retrain, 2026 becomes training data — so **the new model has no
untouched season to be tested on**. Pretending otherwise (retraining on
everything and quoting the old test numbers) is the single easiest way to
ship a model that looks better than it is.

**The rule:** a retrained model ships with *no* headline test number. Its
evidence is the live track record it accumulates from the day it is served,
and the 2027 season becomes its held-out test at the next retrain. The
interface must say "not yet tested on an unseen season" for as long as that
is true.

## Before retraining: explain the negative live skill

The served 1-day model has been losing to persistence on live forecasts all
season, and the number has not settled:

| date | graded | positives | skill vs persistence |
|---|---|---|---|
| 24 Sep 2026 | 175 | 5 | −37% |
| 26 Sep 2026 | 209 | 6 | −4.7% |
| 27 Sep 2026 | 243 | 7 | −1.8% |
| 29 Sep 2026 | 311 | 7 | **−15.6%** |

That is the first thing to understand, because a retrain that ignores it just
re-learns the same mistake. Note the last row: 68 more forecasts, no new
positives, and the skill got *worse* — so whatever is happening is happening
on quiet days, not on floods. Work through, in order:

1. **Is it real, or small numbers?** 7 positives is very few, and the series
   above moves too much to read a trend into. Recompute after the season.
2. **Calibration.** Measured now, and it points somewhere specific:

       cd apps/api && python -m app.services.model.calibrate

   On the held-out season the model says **3.2%** in the band where **2.6%**
   actually happens, while persistence gives an unaffected district 1.9%
   flat. On a long quiet stretch that difference is exactly the kind of loss
   the live record is showing. Check whether the live rows reproduce it
   (`0017`), and if they do, the fix is a threshold or regularisation
   question rather than a feature one — which is item 3.
3. **Which rows lose?** Group graded forecasts by district and by
   affected-today state. Persistence wins the quiet rows for free; if the
   model is losing *there*, it is over-forecasting quiet districts, which is
   a threshold/regularisation problem, not a feature problem.
4. **Fallback rows.** Any row stored as `persistence_fallback` is the
   baseline, not the model. Exclude them before concluding anything.
5. **Distribution shift.** 2026 was wetter/quieter than 2025 in places;
   compare the positive rate per season.

Record the answer in a decision record before changing anything.

## The procedure

```bash
cd apps/api

# 1. Make sure the season is fully ingested, including any missed days.
python -m app.services.ingestion.run --hazard flood --catch-up
python -m app.services.weather.ingest --catch-up
python -m app.services.model.damage_matching

# 2. Look at the numbers without writing anything.
python -m app.services.model.train --dry-run --test-from 2027-01-01

# 3. If the outcome is the one to ship, save it.
python -m app.services.model.train --test-from 2027-01-01
```

`--test-from 2027-01-01` puts both seasons in training. Selection still runs
forward-chaining validation folds inside that history, and still chooses on
validation only — the code refuses to let test numbers into the choice, and
this procedure must not work around that.

Then:

```bash
python -m app.services.model.score --as-of <latest report day>   # re-score roads
cd ../.. && git add -A && git commit -m "Retrain ..." && git push
```

The commit must include the new artifacts: the deployed API reads
`ml/models/*.json` from the image.

## Checklist

- [ ] Both seasons ingested; `/health/ready` shows no stale feed
- [ ] The negative live skill has an explanation written down
- [ ] `--dry-run` output pasted into the decision record, both horizons,
      both feature sets, with the validation scores that drove the choice
- [ ] Artifacts saved, committed and pushed **together** with any code change
- [ ] Roads re-scored so the map matches the served model version
- [ ] `/api/v1/model/status` shows the new version and an empty live record
- [ ] The web copy no longer claims a held-out test the new model has not had
- [ ] Decision record written (next free number), linked from the README

## If the shadow test has reached a verdict

`/api/v1/model/status` → `shadow_test` applies the promotion rule fixed in
`0015`. Only two of its outcomes mean anything:

- **promote** — the rainfall model beat the served one on days neither had
  seen. Retrain *with* rainfall (`train.py` already trains both feature sets
  and picks on validation), note in the decision record that the shadow test,
  not the test season, is what justified it, and freeze a fresh challenger if
  there is a new idea to test.
- **reject** — keep the served features. Record it; a negative result that is
  written down is worth more than one that is quietly dropped.

**undecided** means keep collecting. It is not permission to promote anyway.

## Retraining does not restart the shadow test

The challenger is frozen and never retrained in place. If the served model
changes, the challenger keeps being graded against whatever is served — which
is the comparison that matters. Replacing a challenger (new features, new
freeze date) restarts its count from zero, and
`--freeze-challenger --replace-challenger` is the only way to do it.
