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
3. **`docs/decisions/0003-scenario-engine.md`** — what the what-if engine
   does, its measured results, and exactly what its numbers do and don't
   mean. Read before quoting any travel time.
4. **`docs/decisions/0004-live-hazard-ingestion.md`** — the live data
   pipeline, what makes it safe to run unattended, and the district rename
   that would otherwise have broken it silently.
5. **`docs/decisions/0005-field-report-fusion.md`** — the human layer: how a
   report becomes a belief, how reporter trust moves, and why none of it
   touches `current_accessibility`.
6. **`docs/decisions/0006-corroboration.md`** — where the two live data
   sources meet: why independent evidence may support a report but never
   count against one.
7. **`docs/decisions/0007-current-conditions-routing.md`** — routing from what
   is actually reported now, why Phase 3 is still blocked, and the difference
   between a severed corridor and a blocked driveway.

## Status

Foundation is real; the intelligence layer is mostly still ahead.

**Working end to end on real data:** the road graph (110,266 segments,
47,424 junctions for the Barak Valley corridor), 2025 district flood
severity joined to every road in the four Assam districts that have it, a
baseline accessibility score, PostGIS + a FastAPI serving real queries, an
interactive MapLibre map, and the **scenario engine** — close or flood a
set of roads and get the routing consequence, with the causal trail
(see `docs/decisions/0003-scenario-engine.md`).

**Deliberately minimal:** the accessibility score is a transparent
rule-based baseline (district severity × bridge factor), built to be the
yardstick a future ML model has to beat. That model does not exist yet.

**Live hazard ingestion works** (Phase 2): the DRIMS Assam daily report is
fetched, parsed and stored with provenance and staleness tracking, covering
nine hazard types and including per-district road/bridge damage. See
`docs/decisions/0004-live-hazard-ingestion.md` — it also records that CWC's
bulletin URL, which `0002` planned around, is dead.

**Field-report fusion works** (Phase 2, Tier 1): anyone can report a road as
clear/slow/blocked, reports snap to the nearest segment, and a trust-weighted
vote produces a live field-reported status per road. No personal data — the
reporter id is an opaque device-scoped string. Reports are also checked
against the ingested DRIMS hazard data, so reporter trust no longer rests on
peer agreement alone, which a colluding group could manufacture. See
`docs/decisions/0005-field-report-fusion.md` and `0006-corroboration.md`.

**The live layers now reach the router** (`0007`): a scenario can start from
`current_conditions` instead of a clean graph, deriving closures and
slowdowns from field reports and hazard damage points, graded by how strong
the evidence is. District-level data never closes a road.

**Not started:** Sentinel-1 flood extent, DEM (rest of Phase 2); demand
estimation and logistics optimization (Phase 4); natural-language explanation
(Phase 6). The logistics page is still a scaffold stub (Phase 7). The
accessibility model itself is still the rule-based baseline — neither the
ingested hazard data nor the field reports are wired into
`current_accessibility`, because a district-level daily count and a crowd
vote are both different things from a per-road model prediction, and the
column stays empty until that model exists.

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
