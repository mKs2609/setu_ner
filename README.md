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
8. **`docs/decisions/0008-scheduled-ingestion.md`** — keeping the data
   actually live, why catch-up beats "fetch yesterday", and how to register
   the schedule.
9. **`docs/decisions/0009-terrain-and-satellite-coverage.md`** — terrain per
   road, and an honest account of why Sentinel-1 flood extent is not built.
10. **`docs/decisions/0010-accessibility-model.md`** — the Phase 3 model: what
    it predicts and why, its results against persistence, and why the
    baseline is what is served.
11. **`docs/decisions/0011-demand-and-supply-planning.md`** — Phase 4: demand
    from people actually in relief camps, OSM-located revenue circles,
    exposure-aware routes, and an optimiser that says what is limiting it.
12. **`docs/decisions/0012-explanations-and-audit-trail.md`** — Phase 6: exact
    per-feature explanations, plain-language plan narratives with evidence,
    immutable saved plans and an override log.

## Status

Foundation is real; the intelligence layer is mostly still ahead.

**Working end to end on real data:** the road graph (110,266 segments,
47,424 junctions for the Barak Valley corridor), 2025 district flood
severity joined to every road in the four Assam districts that have it, a
baseline accessibility score, PostGIS + a FastAPI serving real queries, an
interactive MapLibre map, and the **scenario engine** — close or flood a
set of roads and get the routing consequence, with the causal trail
(see `docs/decisions/0003-scenario-engine.md`).

**The accessibility model exists** (Phase 3, `0010`): trained on 312 daily
DRIMS reports across 35 Assam districts and two monsoons, it forecasts
whether a district is flood-affected 1 and 3 days ahead, and
`current_accessibility` is now populated for 71,520 corridor roads — each
value with its model version and as-of date. It is judged against
persistence ("tomorrow looks like today"). After the 2025 population data was
repaired in Phase 4, validation selects **logistic regression for the 1-day
forecast** — a tie with persistence on Brier score, but far better at ranking
new flood onsets (AUC 0.71 vs 0.50) — while **persistence is still served for
3 days ahead**. The per-road spread comes from a stated terrain prior, not a fitted
one. The model has no rainfall input: every free source tried disallows
automated access.

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

**Ingestion is scheduled** (`0008`): a daily catch-up run asks what days are
missing rather than blindly fetching yesterday, so a machine that was off for
a week recovers that week. Setup for Windows, cron and Docker is in
`scripts/scheduling/`. History now spans 312 report days from 1 May 2025.

**The live layers now reach the router** (`0007`): a scenario can start from
`current_conditions` instead of a clean graph, deriving closures and
slowdowns from field reports and hazard damage points, graded by how strong
the evidence is. District-level data never closes a road.

**Terrain is in** (`0009`): elevation and gradient sampled from the Copernicus
DEM for 110,260 of 110,266 roads — the first genuinely per-road feature the
project has. Sentinel-1 **coverage** is tracked too, but **flood extent is
not built**: download needs Copernicus credentials and deriving polygons
needs a real SAR pipeline, so Phase 2 is not complete and is not claimed as
complete.

**Supply planning works** (Phase 4, `0011`): demand comes from the people
DRIMS reports in relief camps and at relief distribution centres, per
revenue circle — not from "population affected", which overstates need about
twentyfold. Circles are located from committed OpenStreetMap data with strict,
reasoned matching. Every depot-to-circle pair gets a fastest and a
lower-exposure route, and an OR-Tools linear programme allocates stock under a
fleet-hours limit, lets the operator choose coverage-first or fairness-first,
and states which resource is binding. Building it found two parser bugs: 5% of
population totals were read from the wrong column, and the entire 2025 season
had no population figures because that year's report labels the section
differently. Both are fixed and the archive re-ingested. Depot stock and fleet
are operator inputs; the example figures are labelled as such everywhere.

**Everything explains itself** (Phase 6, `0012`): a district forecast breaks
down into exact per-feature contributions that add up to the prediction; a
road's accessibility splits into its evaluated district half and its stated
terrain prior; a supply plan comes with a narrative in which every sentence
carries the figures it came from. Sentences are templates filled with real
values — no language model — so an explanation cannot contradict its number.
Plans can be saved as immutable records with model versions, and operators
log overrides with a required, categorised reason.

**Not started:** Sentinel-1 flood extent (rest of Phase 2), which needs a
Copernicus account and a SAR pipeline. Write endpoints (field reports, saved
plans, overrides) are unauthenticated and need auth before real operational
use. Field reports still never write `current_accessibility`.

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
