# 0011 — Demand Estimation and Supply Planning (Phase 4)

**Status:** BUILT. `/logistics` plans water and food runs from depots to
revenue circles, from real reported demand, on routes aware of the Phase 3
forecast. 14 Sep 2026.

`0003` deferred Phase 4 because it "needs population/vulnerability data
nobody has sourced". The data turned out to be in a report this project had
been ingesting for weeks — in sections the parser skipped.

## The demand data was already arriving

Every DRIMS daily report prints, per district **and per revenue circle**:

| Section | What it counts |
|---|---|
| Inmates in Relief Camps | people living in a relief camp (with male / female / children) |
| Non-camp Inmates in Relief Distribution Centres | people drawing supplies without living in a camp |
| Population and Crop Area Submerged/Affected | everyone whose area flooded |

**Demand is built on the first two** — people actually being supplied.
Population affected is shown for context and deliberately not planned for:
on 1 June 2025 Cachar had **103,790 people affected but 5,288 in camps or at
centres**. Planning for the larger number would overstate need roughly
twentyfold. `0001` §2.4 warned that the original demand formula
(population × severity × vulnerability × duration × coefficient) had every
coefficient invented; this uses none of them.

## Two parser bugs found on the way

**1. The population section was read by column position.** pdfplumber
inserts empty cells that shift columns on some rows, so **31 of 613** stored
totals were a component count — Nagaon recorded as 2,534 people instead of
13,463, Cachar as 20 instead of 100. The section prints Male, Female,
Children, then Total, so the total is now found arithmetically: the first
number equal to the sum of the three before it. A row that does not add up
stores nothing rather than a guess. Crop area had the same drift and had
mostly been dropped (22 rows → 615).

**2. The whole 2025 season had no population figures.** The 2025 template
labels the section "Population And Crop Area **Affected**"; 2026 says
"**Submerged**". The parser only knew the second, so 179 report days
silently produced zero population rows — including the June 2025 flood, the
largest event in the archive.

Both were repaired: 2026 from stored raw rows
(`ingestion/reparse_population.py`, no re-fetch), and the full archive
re-ingested once to pick up the 2025 alias and the two inmate sections that
had never been stored. Ingestion is idempotent, so existing rows were skipped
and only new ones written.

## Converting people to quantities

| Commodity | Per person per day | Weight | Basis |
|---|---|---|---|
| Water | 15 litres | 1 kg/L | **Cited** — Sphere Handbook 2018, water supply standard 2.1 |
| Food | 1 ration-day | 0.6 kg | **Derived** — Sphere's 2,100 kcal/day at ~3.5 kcal/g of dry cereals and pulses |

Urgency weights (water 3, food 2) are a **stated judgement**: when both cannot
be covered, a water shortfall is penalised more. Medical supplies are not
included — there is no defensible per-person daily quantity; health kits are
sized for thousands of people over months and belong in a restocking plan.
Every norm can be overridden per plan.

## Where demand is

Demand arrives by revenue-circle **name**. Coordinates come from
OpenStreetMap place nodes, fetched once and committed as
`geo/gazetteer/corridor_places.json` (338 places, ODbL attribution), so
planning never calls a third-party service at runtime.

Resolution is strict:

- **Exact match** ignoring case and diacritics ("Jirighāt" = "Jirighat").
- **Explicit aliases, each with a reason** — 5 of them: Sribhumi Sadar →
  Karimganj (renamed district HQ), RK Nagar → Ramkrishna Nagar, Katigorah →
  Katigora, Patherkandi → Pathar Kandi, Maibang → Maibong. No fuzzy matching.
- **Same-named nodes within 3 km are one place** and are averaged (Algapur is
  mapped twice, 1.2 km apart). Further apart, resolution refuses.
- **Otherwise not located.** Borkhola has no OSM place; its demand is
  reported and not routed.

A circle HQ town is where a supply run is addressed, not where any camp is —
camp locations are not published. A point more than 5 km from the road graph
is not routed either: Katlicherra, south of the corridor's graph, is shown
grey on the map with its 220 people listed as outside the plan, never drawn
as "fully supplied".

The overpass-api.de instance disallows `/api/` in robots.txt; the fetch used
the overpass.kumi.systems mirror, which publishes none (the project client
treats that as allow-all, and it is the mirror the Phase 1 road build used).

## Routes: fastest, and lower-exposure

`0001` Tier 1 item 3 asked for the fastest and the safer route side by side.
Every depot → circle pair gets both:

- **fastest** — least travel time, under live closures and slowdowns (`0007`)
- **lower-exposure** — least of travel time + penalty × exposure-km

**Exposure-km** weights each kilometre by how inaccessible Phase 3 says the
road is (a km at accessibility 0.26 counts 0.74). The penalty — minutes of
detour the operator accepts per exposure-km — is a stated preference, not a
probability. Route "reliability" as a product of per-road accessibilities was
rejected: roads in one district flood in the same event, so treating them as
independent would be wildly pessimistic while looking precise.

On 1 June 2025, Haflong → Udharbond: fastest **160 min, 29.8 exposure-km,
32 bridges**; lower-exposure **214 min, 16.1 exposure-km, 11 bridges**. That
is the choice the screen exists to show.

**Replay:** a past report day plans against that day's demand and what the
model would have forecast then (recomputed from that day's features with the
same artifacts). Live field reports and damage closures apply only when
planning from the latest report.

## The optimiser

A linear programme (OR-Tools GLOP): stock per depot, need per circle, and a
fleet-hours limit per depot (trucks × hours/day × days, where each kg costs
round-trip time plus loading ÷ truck capacity). Unreachable pairs simply have
no variable.

**Priorities are solved in order, not blended into one weighted sum**, so
nobody has to explain what a weight meant:

1. cover the most urgency-weighted person-days;
2. spread any shortfall as evenly as possible (minimise the worst circle's
   shortfall fraction);
3. use the fewest truck-hours.

**The order of 1 and 2 is the operator's choice.** When trucks rather than
stock are short, covering the most need favours nearby circles. On a test
case with one truck: coverage-first covers 5,195 of 6,000 person-days but
leaves the far circle 81% short; fairness-first leaves nobody worse than 43%
short but covers only 3,419. Neither is right in general, so both numbers
are always shown.

**What limits the plan** comes from dual values of the coverage problem and
is written out in plain words — "Stock of water at Silchar is binding: each
extra litre would cover about 0.2 more urgency-weighted person-days", "Trucks
at Haflong are binding: one more truck-hour would cover about 185". These are
marginal values, valid for small changes. This is the first piece of the
Phase 6 explanation layer.

## What it produced

**5 June 2025** — the busiest day in the archive: **153,474 people** in camps
or at relief centres across the corridor, needing 2.3 million litres of water
and 153,474 ration-days in one day. With the example depot stock (105,000 L,
14,500 ration-days, 9 trucks), the plan covers **7%** of need at reachable
circles, every depot's water and food stock is binding, and the worst circle
is 95% short. That is the honest answer to "what can we do with what we
have", and the limits list says exactly which extra resource would help most.

**1 June 2025** — 7,121 people: the same example stock covers **99%**, with
water at Silchar, Karimganj and Hailakandi and Haflong's single truck as the
binding constraints.

## Safety of the inputs and outputs

- **Example stock is labelled everywhere.** Depot holdings and fleets cannot
  be known by the system. The example figures carry a banner until the
  operator edits them, and the response echoes `example_inputs`.
- **Bounded requests.** ≤10 depots, ≤7-day horizon, penalty ≤600, coordinates
  inside the corridor — each depot costs two shortest-path passes over 47k
  junctions, on an endpoint anyone reaching the API can call.
- **Nothing is dropped silently.** Unlocated circles, off-graph circles,
  circle breakdowns that do not sum to the district total ("unattributed"),
  and conflicting duplicate rows are all reported. Sub-1 kg solver residue is
  omitted from the output and its total reported.

## Known limitations

- **No fixed cost per truck.** A linear programme can propose a four-hour run
  for a few hundred litres. Consolidating those needs integer variables (a
  MILP) — future work, stated on screen.
- **Fractional loads.** Truckloads are rounded up per run; fleet time is
  enforced in aggregate, not as a vehicle schedule.
- **Round trips assumed symmetric.**
- **Depots are town centres**, not actual warehouse locations.
- **Demand is as reported.** Reporting lags and gaps in DRIMS pass straight
  through.

## What was built

- `services/logistics/` — `demand.py`, `gazetteer.py`, `routes.py`,
  `optimize.py`, `plan.py`
- `routers/logistics.py` — `/supply-days`, `/demand`, `/example-inputs`,
  `POST /plan` (replacing the stub)
- `geo/gazetteer/corridor_places.json`
- Parser: population by arithmetic, the 2025 label, both inmate sections,
  per-circle breakdowns; `ingestion/reparse_population.py`
- Web: `/logistics` — report-day picker, editable depots, exposure penalty,
  fairness toggle, runs with both routes, shortfalls, limits, and a map
- Compose mounts the gazetteer for the API container

## Testing

25 new logistics tests and 6 new parser tests. The optimiser is tested on
problems small enough to solve by hand — even stock sharing (each circle
exactly one third short), the dual value (urgency 3 ÷ 15 L = 0.2), fleet hours
never exceeded, fairness trading coverage for a better worst case, an
unreachable circle reported rather than supplied. The gazetteer tests pin the
refusal rules. Integration tests assert demand never exceeds people being
supplied and a lower-exposure route never has more exposure than the fastest.

## Next

- MILP dispatch with a fixed cost per truck, if the small-run problem matters
  in use.
- Real depot locations and holdings, from whoever runs the depots.
- Phase 6: the limits and route trade-offs already produce plain-language
  sentences; extending that to every recommendation is the explanation layer.
