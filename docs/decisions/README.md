# Decisions

Lightweight ADR-style log. Numbered, never deleted: a superseded decision
gets a note pointing to the one that replaced it rather than being removed.
Records that document a failure, a blocked data source or a model that lost
to its baseline are kept for the same reason as the ones that worked.

| | |
|---|---|
| `0001-gap-analysis-and-enhancements.md` | Audit of the original plan: what it assumed about data access, and what had to change before any code was written |
| `0002-corridor-selection.md` | Choosing the Barak Valley corridor, and the checks it had to pass |
| `0003-scenario-engine.md` | The what-if engine, its measured results, and what its travel times do and do not mean |
| `0004-live-hazard-ingestion.md` | The daily report pipeline, and the district rename that would have broken it silently |
| `0005-field-report-fusion.md` | Field reports: how one becomes a belief, how reporter trust moves, and why none of it overwrites a score |
| `0006-corroboration.md` | Where two independent sources meet: evidence may support a report, never count against one |
| `0007-current-conditions-routing.md` | Routing from what is reported now; a severed corridor versus a blocked driveway |
| `0008-scheduled-ingestion.md` | Running unattended: why catch-up beats "fetch yesterday" |
| `0009-terrain-and-satellite-coverage.md` | Terrain per road, and why Sentinel-1 flood extent is not built |
| `0010-accessibility-model.md` | The district flood-state model: target, validation, results, and why a baseline is served at 3 days |
| `0011-demand-and-supply-planning.md` | Demand from relief-camp populations, exposure-aware routes, and an optimiser that names its binding constraint |
| `0012-explanations-and-audit-trail.md` | Explanations that reconstruct the prediction; immutable plans and an append-only override log |
| `0013-deployment-readiness.md` | What had to exist before a public URL: tokens, config guard, readiness, migrations, image |
| `0014-rainfall-input.md` | Rainfall: every source re-checked, IMERG built, and why the model using it is not served |
| `0015-shadow-test.md` | Testing the rainfall model on days neither model has seen, under a rule fixed in advance |
| `0016-alerting.md` | Watching the deployment from outside it, because the failure worth catching is the one where nothing runs at all |

Operational procedures live one level up: `docs/deployment.md`,
`docs/retraining.md`, `scripts/scheduling/README.md`.
