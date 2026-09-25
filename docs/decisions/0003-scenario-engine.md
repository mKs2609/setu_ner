# 0003 — Scenario Engine

**Status:** BUILT — routing + what-if working end to end, measured below.

## Why this phase before Phase 3 (ML) or Phase 4 (logistics)

Phase 4 needs population/vulnerability data nobody has sourced. Phase 3's
live model needs live hazard data (today's rainfall/river levels), which
does not exist yet either — `0002` established that both CWC and ASDMA
require scraper/document ingestion that isn't built.

Phase 5 was blocked on nothing. Everything it needs was already in
PostGIS and verified before a line was written: `osm_u`, `osm_v`,
`length_km`, `assumed_speed_kmh` and `baseline_travel_time_min` are
populated for all 110,266 edges. It also builds the routing layer Phase 4's
optimizer will need regardless, so the work is not throwaway.

## What was built

- `app/services/routing/graph.py` — routable graph from PostGIS, cached
  per process.
- `app/services/routing/landmarks.py` — six named corridor places.
- `app/services/scenario/engine.py` — closure/degradation simulation.
- `app/routers/scenarios.py` — `GET /landmarks`, `GET /route`,
  `POST /simulate`.

## Measured results (6 Sep 2026, local, real corridor data)

Graph: **47,424 junctions, 109,522 node pairs, 110,266 roads**, built in
**~0.5–1.6 s**, cached process-wide. The corridor is a **single weakly
connected component (100% of nodes)** — no orphan islands, so routing
between any two corridor points always has a baseline.

Landmark snapping — all six land within **330 m** of a graph junction
(Silchar 12 m, Haflong 8 m, Kalain 328 m), confirming both the hand-entered
coordinates and graph density are adequate.

| Scenario (Silchar → Haflong unless noted) | Result |
|---|---|
| Baseline | 94.4 min, 87.4 km, 158 segments, 26 bridges |
| Close 26 bridges on that route | 215.3 min — **+120.9 min, +128.2%**, +36.8 km detour |
| Close all 1,509 Cachar bridges | **SEVERED** — no route exists |
| Close all 372 Karimganj bridges | **No change** — 0 of them on the route |
| Route flooded, 3× slower (degrade) | +92.5 min, +98.1% |
| Silchar → Kalain baseline | 32.7 min, 23.2 km, 4 bridges |
| Close only those 4 bridges (2025 event replay) | **+19.9 min, +60.8%**, +22.8 km detour |

Every simulation solves in **0.04–0.07 s** — fast enough to run live in a
request, no precomputation needed.

## Decisions and the reasoning behind them

**1. Report deltas, label absolutes as modelled.** Travel times inherit
`assumed_speed_kmh`, a per-road-class assumption, not measurement. The
delta between two routes over the same graph is robust because the
assumption applies to both sides and largely cancels; the absolute is not.
Every API response carries this caveat inline, the same way
`baseline_accessibility_basis` / `_confidence` travel with the score —
the qualification has to reach the operator, not sit in a docstring.

**2. Parallel roads are kept, not collapsed.** 110,266 roads collapse to
109,522 node pairs, so 744 are parallel alternatives. Collapsing to the
fastest would mean closing one road severs a link that a real parallel
road still serves. Each edge holds all its alternatives and dies only when
all are closed. Unit-tested directly, because it is invisible at 110k scale.

**3. Closures are bidirectional by default.** `build_road_graph.py` wrote
one row per direction. Closing only the named row leaves the opposite
carriageway of a collapsed bridge standing — plausible-looking and wrong.
Default `true`; `false` remains available for genuine one-way closures.

**4. "No change" is a real, reported answer.** Closing 372 Karimganj
bridges and reporting the truth — that none were on the route — matters
more than producing an impressive-looking number. The response names which
closed roads were actually on the baseline route; a large closure count
with an empty list means the scenario missed.

**5. Severance is a result, not an error.** `NetworkXNoPath` becomes a
structured "CUT OFF" verdict. That case is the corridor's headline finding,
not a failure.

**6. Snap distance is always reported.** Origin/destination snap to the
nearest junction; the response says how far. A bad coordinate shows up as a
large snap instead of hiding inside a plausible answer.

## Honest limitations

- **Travel times are modelled free-flow, dry-condition.** No measured speed
  data exists for this corridor.
- **Landmark coordinates are hand-entered approximations**, not gazetteer
  data. Replace with Survey of India / LGD before any published figure
  depends on them. All six currently snap under 330 m.
- **One-way and bridge tags come straight from OSM**, still not
  hand-verified — the open item from `0002` is still open.
- **The scenario does not recompute accessibility scores**, only routes.
- **This is not a logistics plan.** No demand estimation, no allocation.
  That is Phase 4 and it is not built.

## Testing

26 new tests, 28 in the suite. **17 unit tests run without a database** on a
hand-built synthetic graph, covering parallel-road fallback, bidirectional
expansion, severance, degradation, and the causal explanation. 9 integration
tests hit the real corridor and skip cleanly when no database is reachable —
CI has neither Postgres nor the corridor data, since the geo outputs are
gitignored.

Runs: 28 passed with a database; 19 passed / 9 skipped without one.

## Also fixed (pre-existing, found while wiring CI)

- `.github/workflows/ci.yml` filtered on `@sih26002/web`, but the package
  was renamed to `@setu_ner/web` in `c283b3c`. pnpm matched no project and
  **exited 0** — so web lint, type-check and build had been silently not
  running, with CI green.
- `turbo.json` used `pipeline`, renamed to `tasks` in Turbo 2.x, so the
  documented root `pnpm dev` / `pnpm build` errored out.

## Scenario UI (Phase 7, added after this engine landed)

`/scenarios` is now a real workbench: pick origin and destination from the
landmark list, choose a district, and either collapse or flood its bridges.
Both routes are drawn on the map — baseline in muted blue, scenario in amber
dashes — so an overlap reads as "no detour" and a divergence reads as one.

The screen deliberately keeps three things the API returns that a tidier UI
would drop: the plain-language verdict (including "no change"), the causal
count of how many closed roads were actually on the baseline route, and the
modelled-time caveat behind a disclosure. Hiding any of them would make the
screen look more certain than the data under it.

One backend addition came out of building it: `degrade_bridges_in_district`,
symmetric with `close_bridges_in_district`. Without it the "flooded but
passable" case was only reachable by passing explicit road ids, which a UI
has no way to know. A road named by both is closed, since that is the
stronger claim.

## Next

Live hazard ingestion (the rest of Phase 2) is the blocker for everything
above it — the accessibility model cannot be trained without it.
