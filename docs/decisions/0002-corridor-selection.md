# 0002 — Study Corridor Selection

**Status:** LOCKED (provisional) — see Decision below.

## Candidate

Silchar/Cachar ↔ rest of Assam, via Dima Hasao (Haflong) and the Meghalaya
NH-6 route. See `0001-gap-analysis-and-enhancements.md` §8 for why this is
a strong candidate: three real recurring failure modes (2022 dyke breach,
2024 Cyclone Remal, 2025 bridge collapse), impact reaching beyond Assam
(Tripura, Mizoram, parts of Manipur depend on the same chokepoint), and a
free historical-replay dataset from public reporting.

## What has to be true for this to be locked in

- [x] `check_cwc_nwdp_access.py` shows real, reachable rainfall/river-level
      data with stations near Cachar / Dima Hasao — not just national
      coverage in principle.
- [x] `check_asdma_access.py` shows Flood Alert / Flood Report content
      that's actually usable (even if it needs PDF parsing) and covers the
      right districts.
- [ ] OSM road-graph quality for the corridor has been spot-checked by hand
      (bridge flags, surface type) — don't trust the tags blindly.
- [ ] The corridor genuinely fits in the SIH demo (§28 of the master
      reference): 5 minutes, one bridge-closure scenario, one rain/river
      what-if.

## Results log

```
CWC/NWDP check (23 Aug 2026): 3/5 endpoints reachable (NWDP portal root,
NWDP river-level dataset page, CWC flood forecasting portal), all served
as HTML -- no JSON/REST API found anywhere. India-WRIS timed out on both
attempts. ffs.india-water.gov.in resolving is the key finding: same
portal the GUARDIAN research paper scraped for near-real-time data.
Conclusion: ingestion must be a scraper against ffs.india-water.gov.in
and/or the NWDP dataset pages, with retry + staleness tracking. No clean
API exists -- confirmed, not assumed.
```


## Decision

Locked (provisionally): Silchar/Cachar <-> rest of Assam via Dima Hasao
and NH-6 (Meghalaya). Data-access checks (23 Aug 2026) confirm both CWC
and ASDMA sources are reachable, though neither is a clean API -- both
require scraper/document-parsing ingestion, as anticipated. District-level
coverage for Cachar/Dima Hasao specifically hasn't been hand-verified yet
(open item), but the underlying case for this corridor (recurring
2022/2024/2025 disruption events) doesn't depend on that. Proceeding with
this corridor; will revisit only if the district-level check turns up
nothing usable.