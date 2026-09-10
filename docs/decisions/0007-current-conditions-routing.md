# 0007 — Routing From Current Reported Conditions

**Status:** BUILT — the live layers now reach the router. 10 Sep 2026.

## Why not the Phase 3 model, which `0006` named as next

`0006` said the next step was the accessibility model, now that hazard
history was accumulating. Checked before starting, and it is not true yet:

| | |
|---|---|
| Labelled (road, day) pairs | **3** |
| Distinct roads ever reported | **2** of 110,266 |
| Field reports total | 22, mostly test data |
| In-corridor hazard observations | 107, all district-level |

A per-road accessibility model trained on three examples would be theatre.
It would produce numbers, they would look like predictions, and they would
mean nothing. Phase 3 stays blocked on data volume, not on effort.

## The gap that was actually worth closing

The scenario engine had always routed on a **clean graph**. Every closure had
to be typed in by hand. So the project ingested a daily hazard bulletin
(`0004`), collected field reports (`0005`) and corroborated them (`0006`) —
and none of it had ever touched a routing decision.

The project's pitch is that existing systems tell you a flood is happening
while nothing tells you which road will still work when your truck gets
there. Answering that requires the live layers to reach the router. Now they
do: `start_from: "current_conditions"` on `/simulate`, plus
`GET /scenarios/current-conditions` to inspect the live state directly.

## A graduated response, not a switch

Removing a road from the network is a strong claim — it can sever a corridor.
One person saying "blocked" is real evidence and should be visible, but it
should not by itself delete a highway from the map.

| Evidence | Effect |
|---|---|
| Blocked, weight ≥ 1.0 (≈ two fresh reports, or one trusted reporter) | **Closed** |
| Blocked, weight ≥ 0.45 **with independent corroboration** | **Closed** |
| Blocked, below threshold | Slowed 6× — avoided unless nothing else works |
| Reported slow | Slowed 2.5× |
| Hazard damage point within 2 km | Slowed 1.8× |

Corroboration from `0006` lowers the bar to a single credible report, because
evidence nobody submitting reports controls is worth more than another show
of hands.

**District-level hazard data never closes a road.** "Cachar reported four
damaged roads" does not identify which four out of fifty-one thousand.
Letting that close anything would invent specificity the source does not
have. Only a geolocated damage point can put a specific stretch of road under
suspicion, and even then it only slows it. There is a test asserting this.

## Two bugs found while building it, both silent

**Per-road factors were being flattened.** The engine took one uniform
`degrade_factor` for all degraded roads, so the entire graduated design above
was discarded the moment it crossed into `simulate()` — every road slowed by
the same 2.0, no error anywhere. The engine now accepts either a set (uniform)
or a mapping (per-road), and the router preserves the mapping through
bidirectional expansion, which was flattening it a second time. Tested at
every layer it passes through, because it failed twice.

**The spatial query took 34 seconds.** Casting to `::geography` for an exact
distance is correct and unindexable, so Postgres was scanning all 110,266
roads on every call. Screening with `&&` against an expanded bounding box uses
the GiST index, and the geography check refines the survivors. Same answers,
**0.02 s** — and the test suite went from 108 s to 2.7 s.

## The overstatement this surfaced, and the fix

Routing from current conditions immediately produced: *"Silchar is CUT OFF
from Haflong."*

True in graph terms — and badly misleading. The one closed road was 29408,
which is the road the Silchar origin itself snaps to. Every road out of that
junction was closed, so nothing could set out. That is a completely different
operational situation from the corridor being severed somewhere in the middle,
and it is the case live conditions will hit most often: a field report lands
at somebody's location, so the road it snaps to is the origin's own access
road.

The engine now diagnoses *why* there is no path — `origin_isolated`,
`destination_isolated`, `both_isolated`, or genuine `severed` — and both the
detailed reason and the headline verdict say which. The origin case now reads:

> Nothing can set out from Silchar: every road leaving its junction is closed
> under this scenario. This is a local blockage, not the corridor being
> severed.

Getting this wrong would have been the most damaging kind of error this
system can make: a dramatic, confident, wrong headline.

## Honest limitations

- **Coverage is almost nothing.** One road currently has enough reports to be
  closed, out of 110,266. Silence about a road means nobody has reported it,
  *not* that it is known to be open. The response says so.
- **Today's closure rests on test data.** The 11 reports on road 29408 are
  largely ones I submitted while building. The mechanism is real; the current
  content is not field data.
- **The baseline stays clean.** A current-conditions simulation compares
  against the undamaged network, so the delta includes the conditions
  themselves as well as any closure you add. `starting_conditions` lists what
  was already applied, and a caveat says this.
- **Reports are not verified before they close a road.** Two coordinated
  reports meet the closing threshold without corroboration. Trust weighting
  and the corroboration path from `0006` limit this, they do not remove it.
- **Still nothing writes `current_accessibility`.** Unchanged since `0005`.

## Testing

15 new tests, 113 in the suite. The per-road factor plumbing is tested at
every layer, the graduated thresholds are asserted against each other, and
the no-path diagnosis has a case per outcome. One existing test changed: it
asserted the wording "CUT OFF" for a case that is now correctly reported as
an isolated destination.

## Next

Phase 3 still needs data volume. The two things that would actually move it:
schedule the daily ingestion so hazard history keeps accumulating without
someone running a command, and get real reporters onto the field-report
screen. Neither is a modelling problem.
