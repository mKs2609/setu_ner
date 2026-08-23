# SetuNER — NER Accessibility & Logistics Intelligence Platform

Built for SIH 2026 · Problem Statement SIH26002 · Software · Smart Automation · Ministry of Development of North Eastern Region (MDoNER)

Repo: `setu_ner`

Forecasts how accessibility across the North Eastern Region's road network
changes under hazard conditions, estimates critical demand, optimizes
resource movement under constraints, and lets an operator test what-if
scenarios — starting with floods, architected to extend to other hazards.

## Start here

1. **`docs/decisions/0001-gap-analysis-and-enhancements.md`** — the audit of
   the original master reference plus the differentiators baked into this
   build. Read this before touching the data or model layers.
2. **`docs/decisions/0002-corridor-selection.md`** — study corridor is
   locked (provisionally): Silchar/Cachar via Dima Hasao and NH-6.
3. **`scripts/data-access-checks/`** — the throwaway scripts already run;
   see 0002 for results. Re-run if data sources need re-verifying later.

## Status

Scaffold stage. The FastAPI backend boots and its test suite passes; every
router beyond `/health` is an honest stub. The Next.js frontend has route
placeholders only — visual design is deliberately deferred until the core
data → accessibility → optimization → explanation loop works end to end.

## Repo layout

apps/
web/ Next.js frontend (App Router, TS, Tailwind, MapLibre/deck.gl)
api/ FastAPI backend
packages/ Shared TS types/UI, if/when needed across apps
data/ raw / processed / samples (raw and processed are gitignored)
ml/ datasets, features, training, evaluation, models
geo/ OSM, DEM, rainfall, river, satellite processing
optimization/ routing, allocation, scenario logic
scripts/ ingestion, preprocessing, dev helpers, data-access-checks
docs/ architecture, data, ml, api notes, and numbered decisions
infra/ docker, migrations


## Local development

```bash
# 1. Copy env files
cp .env.example .env
cp apps/api/.env.example apps/api/.env

# 2. Install
pnpm install
cd apps/api && pip install -r requirements.txt && cd ../..

# 3. Bring up Postgres + PostGIS
docker compose up postgres -d

# 4. Run the API
cd apps/api && uvicorn app.main:app --reload --port 8000

# 5. Run the web app (separate terminal)
cd apps/web && pnpm dev
```

API docs: http://localhost:8000/docs · Web app: http://localhost:3000

## Git strategy

`main` — stable/demo-ready. `develop` — integration. Feature branches:
`feature/road-graph`, `feature/rainfall-ingestion`,
`feature/accessibility-model`, `feature/scenario-engine`,
`feature/logistics-optimizer`, `feature/map-dashboard`,
`feature/field-report-fusion`. PRs into `develop`; protect `main` once the
team's comfortable with the workflow.

## Evaluation discipline

No fabricated numbers, ever. Every metric in a pitch or a doc comes from an
actual experiment logged in `docs/ml/`.
