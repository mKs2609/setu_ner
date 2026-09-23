# 0005 — Field-Report Fusion Layer (Phase 2, Tier 1)

**Status:** BUILT — submission, snapping, trust scoring and fusion working
end to end, with a UI. Verified 9 Sep 2026.

## Why this before the ML model or the optimiser

`0001` section 4 calls this "the layer that's genuinely missing: humans" and
says the data matrix treating field data as a footnote is "backwards from
what's actually being asked for". The original brief asks for AI/ML and GIS
**and real-time field inputs**. It is Tier 1 differentiator #1 in our own gap
analysis.

It is also the only remaining Tier 1 item blocked by nothing: no external
data source, no trained model, no population figures. And it is the 2022
Bethukandi case — an on-site engineer reported the dyke breach by radio
before it appeared in any feed. Official telemetry across the NER is sparse
enough that human reports are not a UX nicety; they are how the gap gets
filled.

## What was built

- `services/fusion/reports.py` — snapping, trust scoring, fusion.
- `routers/field_reports.py` — submit, recent, per-road view.
- Tables `field_reports` and `reporters`.
- `/field-reports` — a real screen: report form, live map, fused view.

## How a report becomes a belief

1. **Snap.** The report's coordinate is matched to the nearest road segment
   using the PostGIS KNN operator, with the true distance computed on the
   geography type so it is metres rather than degrees. Silchar town centre
   snaps 12 m; a point in Kolkata snaps 440 km.
2. **Guard.** Beyond 250 m the report is stored but excluded from fusion.
3. **Weight.** Each report in the last 24 hours votes for its status,
   weighted by the reporter's trust *at submission* and by how recent it is.
4. **Conclude.** The heaviest status wins; confidence is its share of total
   weight, so a genuine split scores low.

Verified live: four reports on one road (two blocked, two clear) produced
**blocked at 0.526 confidence** — correctly reported as a near-split rather
than false certainty.

## Trust

```
trust = 0.5 + 0.5 * (corroborated - contradicted)
                   / (corroborated + contradicted + 4)
```

New reporters start at 0.5, not 0 — a newcomer's first report about a
collapsed bridge should be visible, just not decisive. The `+ 4` prior damps
the update so one disagreement after a long good run is a nudge, not a
cliff. Bounded to [0.05, 0.95]: nobody reaches certainty, and nobody is
silenced completely, because a reporter who has been wrong before may be the
first to see something real.

Verified: agreeing moved a reporter 0.5 → 0.6; disagreeing twice moved
another 0.5 → 0.33.

The API returns *why* trust moved (`corroborated` / `contradicted` /
`no_consensus`) and the UI says it in words. A score that moves invisibly is
the kind of thing people rightly distrust.

## Decisions worth defending

**1. No personal data, deliberately.** The reporter id is an opaque
device-scoped string the browser generates and keeps in `localStorage` — not
a name, phone number or account. People best placed to report a washed-out
road are often standing in a disaster zone; demanding identity gets fewer
reports and creates a record that could be misused. Trust needs continuity
of identity, not knowledge of it.

**2. Nothing here writes `current_accessibility`.** That column stays empty
for the Phase 3 model. Writing a crowd consensus into it would blur the
observed/derived line the project holds everywhere else — an operator
reading "0.2" could not tell whether it came from a trained model or from
two people with phones. The fused status is published as its own field, next
to the historical baseline, both labelled. There is a test asserting the
column stays empty.

**3. Reports are observations, never overwritten.** Stored verbatim; the
fused view is derived at read time. A wrong or malicious report can be
reweighted or excluded later without the original having been lost.

**4. Trust is frozen at submission.** Trust moves afterwards. Freezing the
value on each report is what keeps an old fused result reproducible instead
of silently shifting.

**5. Out-of-corridor reports are kept, not discarded.** They are excluded
from fusion and drawn hollow on the map. A cluster of them is a real signal
— a GPS problem, or people reporting from somewhere the road graph does not
cover. Discarding them would hide that.

**6. Manual coordinates are a first-class input.** Not a developer
convenience: GPS fails under tree cover and in the steep terrain this
corridor is full of, and a control room relaying a report by phone has
coordinates but no device fix. Refusing those would lose exactly the reports
that matter most.

## Honest limitations

- **It is gameable.** Trust rises when a report agrees with other recent
  reports on the same road, so colluding reporters corroborate each other
  upward. Fixing it properly means corroborating against *independent*
  evidence — satellite flood extent, the DRIMS damage rows from `0004` —
  rather than against other reports. That is Phase 3 work. The MVP is a
  weighted vote and says so.
- **The rate limit is not security.** 30 reports per hour per reporter id
  stops a retry loop or one over-enthusiastic client. An opaque id is
  trivially rotated; this is hygiene, not defence.
- **No photo upload.** The stub's `photo_url` was dropped rather than left
  as a field that silently does nothing.
- **Fusion is a weighted vote, not a Bayesian update.** `0001` section 4
  names the Bayesian version as the natural v2; each report as a noisy
  observation with a reporter-specific likelihood.
- **Integration tests write to the dev database.** They leave test reporters
  in the trust ledger. Harmless on a regenerable dev database, but the right
  fix is a transaction-rollback fixture or a separate test database.

## Testing

20 new tests, 77 in the suite. The pure-function half — trust bounds and
damping, the consensus rule, recency decay — runs without a database in CI,
because that is where the judgement lives and where a reviewer will push.
Integration tests cover snapping, the distance guard, the fused response
shape, and that `current_accessibility` stays empty.

## Next

Two candidates, both now unblocked in a way they were not before:

- **Corroborate reports against the DRIMS damage rows** from `0004`. The
  ingested per-district road and bridge damage counts are independent
  evidence, which is exactly what the trust model currently lacks.
- **Phase 4**, if population data can be sourced — though note DRIMS now
  supplies `population_affected` per district, which is a real start.
