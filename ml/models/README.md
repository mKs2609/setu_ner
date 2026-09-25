# models

Trained model artifacts, committed because they are small and reviewable.

- `district_flood_state_h1.json`, `district_flood_state_h3.json` — the served
  district flood-state model (docs/decisions/0010). JSON rather than pickle:
  loading cannot execute code, and each file carries its own training period,
  held-out metrics, baselines and verdict.

Regenerate with `python -m app.services.model.train` from `apps/api`.
Large binary models (if ever needed) belong in object storage; `*.pkl` and
`*.joblib` stay gitignored.
