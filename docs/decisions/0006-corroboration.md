# 0006 — Corroborating Field Reports Against Hazard Data

**Status:** BUILT — verified against 20 days of real DRIMS data, 10 Sep 2026.

## The hole this closes

`0005` shipped a trust model that judged a report against *other recent
reports on the same road*. That is circular. Several people agreeing with
each other raise each other's scores, so a small colluding group can
manufacture trust out of nothing. The limitation was written down at the
time, and the fix named: corroborate against evidence nobody submitting
reports controls.

`0004` had already produced exactly that. The DRIMS daily reports carry
per-district road, bridge and embankment damage plus geolocated damage
points, published by district administrations. A group gaming the report
form has no way to put a damage row in a government bulletin.

This is the first time two independent data sources in this project talk to
each other.

## The asymmetry, which is the whole design

**Independent evidence may corroborate a report. It may never contradict
one.** That is not caution for its own sake — it follows from what the
source actually is:

- **It lags.** DRIMS is compiled daily from district submissions. In the 2022
  Bethukandi dyke breach an on-site engineer reported it by radio before it
  appeared in any feed. A rule that penalised him for being ahead of the
  bulletin would punish precisely the reports worth the most.
- **It is coarse.** District counts say nothing about one road. "Cachar
  reported zero damaged roads" is not a claim that a particular road is fine.
- **It is narrow.** A road can be impassable with no "damaged infrastructure"
  to report — a fallen tree, standing water, landslide debris.

Absence of evidence here is genuinely not evidence of absence, and the code
treats it that way: finding nothing leaves trust exactly where peer
consensus put it.

## What it changes

Two things, both aimed at the collusion hole:

1. **A report with independent backing counts as corroborated even with no
   peers.** An honest lone reporter no longer needs company to build trust.
2. **A report with independent backing cannot be penalised by peers
   disagreeing.** A group can outvote a lone honest reporter; they cannot
   outvote a government damage bulletin.

The rule lives in one pure function, `decide_outcome(peer_consensus,
report_status, independently_supported)`, tested across every combination of
its inputs.

| Peers | Independent evidence | Outcome | Basis |
|---|---|---|---|
| agree | supports | corroborated | both |
| agree | none | corroborated | peers |
| none | supports | corroborated | independent_evidence |
| none | none | no_consensus | none |
| **disagree** | **supports** | **corroborated** | **independent_evidence** |
| disagree | none | contradicted | peers |

That fifth row is the anti-collusion property, and it has its own test.

## Clear reports are neutral, not contradicted

Damage evidence supports "blocked" and "slow". For "clear" it is deliberately
neutral — a specific road can be perfectly passable in a district that is
flooding elsewhere, and scoring that as a contradiction would punish accurate
good news.

## Evidence tiers and their weights

| Evidence | Weight | Reasoning |
|---|---|---|
| Damage point within 2 km of the road | 0.60 | Names specific broken infrastructure at roughly the right place |
| District reported road/bridge/embankment damage | 0.30 | Right district, right kind of event, wrong resolution |
| District flood impact (villages, population, affected flag) | 0.15 | Weakest — says a district is in trouble, not which road |

Support threshold is **0.30**, calibrated so a district merely being
flood-affected is *not* on its own enough to corroborate a specific road,
while reported infrastructure damage in that district is. That boundary is
the point of the numbers.

The weights are judgement calls, not measurements, and are flagged as such in
the API response — the same treatment the 0.7 bridge factor gets in the
baseline score.

## Different evidence decays at different rates

A flat lookback would have been the easy choice and the wrong one:

| Evidence | Window | Why |
|---|---|---|
| District flood impact | 72 h | A statement about today; stale within a day or two |
| Infrastructure damage | 7 days | A statement about repair work, which is not done in three days |
| Damage point | 14 days | Names specific broken infrastructure; it stays broken until mended |

## Verified on real data

Backfilled **20 days of DRIMS flood reports** (2026-08-20 to 09-08) —
692 observations, 33 geolocated damage points. `0004` said to accumulate a
few weeks before the next step; this is that.

- The spatial tier works: a DRIMS damage point sits **36 m** from road 45306
  in Cachar. With a window wide enough to include it, that road scores
  **1.00** — damage point, plus 4 district roads damaged, plus the affected
  flag.
- **On today's data it correctly scores 0.15 and does not support.** Cachar's
  real damage was reported on 23 and 26 August, 15 and 18 days ago, outside
  both the 7-day and 14-day windows. The late-August flood has receded and
  only the district-affected flag is still live.

That second result is the honest one and it was left alone. Widening a window
until the demo looked better would have been trivial and would have made
every number the system produces worth less.

## Honest limitations

- **No corroboration available right now.** The mechanism is built and
  tested; today's corridor conditions simply do not produce strong evidence.
  It will matter during an actual flood, which is when it is needed.
- **Corroboration is one-directional by design.** A reporter who consistently
  invents blockages that no bulletin ever confirms is still only caught by
  peers disagreeing. Detecting a lone fabricator with no peers is not solved.
- **A determined attacker can still farm trust on quiet roads** by reporting
  "clear" repeatedly where others also say clear. The value of that trust is
  limited, but it is not zero.
- **2 km is generous** for matching a damage point to a road. District-supplied
  coordinates are not surveyed, and at that radius a point can bear on several
  nearby roads. The response reports the actual distance so a reader can judge.
- **Still nothing writes `current_accessibility`.** Unchanged from `0005`,
  and still deliberate.

## Testing

18 new tests, 95 in the suite. The truth table and the weight calibration run
without a database in CI. Integration tests cover the spatial match, window
exclusion of stale evidence, the neutral treatment of "clear", and the API
surfacing its own reasoning.

## Next

The obvious remaining piece is the reverse direction: using accumulated field
reports and hazard observations together as **features for the Phase 3
model**, which now has 20 days of real hazard history and a growing report
log to train against. That is the first point at which "the model" stops
being a placeholder.
