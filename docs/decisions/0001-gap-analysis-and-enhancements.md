# 0001 — Gap Analysis & Enhancements

> Written at the start of the project as an audit of the original brief and
> plan. Kept as written: later records say what actually happened.

This is the audit-and-upgrade pass on the original plan: what it got right, where it assumed access it did not have, and what had to change before any code was written.

---

## 1. Data reality check (verified against real sources, Aug 2026)

The Data Collection Matrix (v2.0 §5) is directionally right but treats access as solved. It isn't. Before writing any ingestion code, know this:

**CWC / National Water Data Portal (rainfall + river level)**
- The data is real, but it isn't a clean live API. The National Water Data Portal (nwdp.nwic.gov.in) serves it as periodic CSV batch downloads segmented by river basin and time window (e.g. "1991–2020", "2021–2025"), not a streaming endpoint.
- A peer-reviewed hydrology paper (GUARDIAN, *Scientific Data*, 2024) had to build a web-scraping pipeline against the CWC flood portal specifically because near-real-time discharge data isn't otherwise accessible in usable form, and even the "historical" WRIS record has significant gaps.
- CWC splits rivers into "classified" transboundary basins (Ganga, Brahmaputra, Indus) with different data-availability rules than "unclassified" rivers. The Brahmaputra — the river that defines Assam's flood risk — sits in the more restricted classified bucket.
- **Action:** design the rainfall/river ingestion service as a resilient scraper/poller with retry logic, staleness flags, and a documented fallback (cached last-known value + an explicit "data is N hours stale" indicator in the UI) from day one. Don't assume a REST client is sufficient. Budget real time for this.

**ASDMA / NESAC — a source the current matrix is missing entirely**
- Assam State Disaster Management Authority is real, active, and already performs a version of what this platform augments: it issues Flood Alerts built on hydro-meteorological analysis from NESAC (North Eastern Space Applications Centre, Shillong) — a NER-specific remote sensing body worth adding as a named source.
- ASDMA + NRSC have jointly produced district-wise flood hazard maps for Assam from satellite data.
- Outputs (Flood Alerts, Flood Reports, Flood Memoranda) look bulletin/PDF-shaped, not API-shaped.
- **Action:** add ASDMA/NESAC as a named source. Build a lightweight document-ingestion path (structured PDF/bulletin parsing) alongside the structured-feed ingestion path — both patterns will be needed regardless of hazard type.

**Sentinel-1 / Copernicus** — access itself is fine (free, open, day/night and all-weather capable). The real bottleneck, which the original doc already half-acknowledges, is SAR processing expertise, not access. Keep Model C optional; don't let it block the vertical slice.

**OSM/Geofabrik** — good foundation, but NER road-attribute completeness (surface type, bridge flags, lane count) is inconsistently tagged outside major highways. Expect to hand-correct/enrich the study corridor's graph rather than trusting OSM tags blindly beyond geometry.

---

## 2. Four concepts the original doc names but never defines

### 2.1 — What *is* "accessibility," formally?
v2.0 §4/§7 use "current accessibility, predicted accessibility" as edge attributes without specifying the type. This decides everything downstream:
- Binary (open/closed) → Model A is a classifier, optimization treats it as a hard constraint.
- Continuous (0–1 reliability) → Model A is a regressor/probabilistic classifier, optimization needs an expected-value or risk-aware objective.
- Categorical (open/degraded/closed) → needs an ordinal model and different UI treatment.

The §3 example ("41% predicted reliability") implies continuous, but nothing else commits to that. **Fix:** define the edge state now — a continuous reliability score in [0,1], a derived categorical status for the UI/legend, and an explicit confidence band. Write this into the schema before the first migration.

### 2.2 — The routing problem is self-referential
This is the sharpest technical gap in the document — and the best hidden differentiator if solved deliberately.

A vehicle's arrival time at edge E depends on the route it took to get there. But "predicted accessibility of E" is a function of *when* you arrive — different at 2pm than at 8pm. Naive Dijkstra over one static "predicted-at-T0" weight per edge is wrong past the first hop, because you're scoring E against a time that isn't when you'll actually be there.

This is a known field: **time-dependent shortest path**. The full academic machinery (time-dependent contraction hierarchies, etc.) is overkill for NER-scale graphs, but a real answer is needed:
- Have Model A output a short forecast vector per edge (accessibility at t+1h, +3h, +6h, +12h, +24h) instead of one point estimate.
- Route with a label-correcting approach that estimates arrival time at each node, looks up the forecast at *that* time (interpolating between horizon buckets), and — since the ETA estimate changes as the route is built — runs 2–3 fixed-point passes until the route stabilizes. This converges fast on road-network-sized graphs and is buildable in-timeline.

Worth stating explicitly. Most projects building "AI-powered routing" will silently do static-weight shortest path. Doing this correctly, and being able to explain why in the bridge-closure demo, is a real technical moat.

### 2.3 — Confidence is decorative unless wired end-to-end
"Confidence" appears as an edge attribute (§7) with no traced origin. Weather-forecast uncertainty should visibly propagate: forecast confidence → accessibility model confidence → route reliability confidence → optimization's risk posture → the explanation drawer. **Fix:** treat uncertainty as a value that flows with the prediction, not a UI decoration added at the end.

### 2.4 — The demand formula has no calibration path
`Population × severity × vulnerability × duration × commodity coefficient` (§8) is a reasonable form, but every coefficient is currently invented. "Calibrated against historical events where data permits" (§24) is a soft hedge repeated three times in the original doc. **Fix:** commit to a specific calibration source now (§8 below gives this for free) and make commodities first-class — medical supplies and food don't decay in urgency the same way; give each commodity type its own time-decay curve instead of one generic demand number.

---

## 3. The multi-hazard promise contradicts the actual architecture

§1 states explicitly: *"We are not building… a flood-only predictor"* and *"the architecture must remain extensible to landslides, severe weather, bridge failures."* Then §8's Model A feature list (rainfall accumulation, river-level trend, flood proximity) and the DB schema (§16: rainfall_observations, river_levels, flood_observations — no landslide/seismic equivalents) are entirely flood-specific with zero extension hooks. The ambition and the spec disagree.

**Fix — a pluggable hazard-module interface, not a bigger flood model:**
- A `hazard_events` table: `hazard_type, geometry, severity, source, observed_at, confidence, provenance` — hazard-agnostic.
- A shared feature-extractor interface (e.g. an abstract `HazardFeatureExtractor`) with one implementation per hazard type (`FloodFeatures`, later `LandslideFeatures`, `SeismicFeatures`), all emitting into the same feature contract Model A consumes.
- Still only *build* flood for now — that is the correct scope call — but "extensible" becomes an architecture fact rather than a claim, and it is checkable.

---

## 4. The layer that's genuinely missing: humans

The **original brief** explicitly asks the platform to combine AI/ML/GIS with weather data *and real-time field inputs* — not satellite/telemetry alone. The current data matrix treats field data as a footnote ("government/field data where available"). That's backwards from what's actually being asked for, and it's the biggest real-world-impact lever available, because official telemetry in NER is genuinely sparse (§1) — human reports are how the actual data gap gets filled, not just a UX nicety.

There's real regional precedent: a community-based flood early-warning system has operated since 2013 on the Singora and Jiadhal rivers in the Assam Himalayan foothills (ICIMOD/Aranyak), where local sensors trigger warnings sent to downstream communities. That proves the *pattern* (local ground-truth → warning) is trusted in this exact region. What doesn't exist anywhere is the next step: turning that ground truth into a routing and resource-allocation decision. That's the real white space (see §6).

**Fix — a field-input fusion layer (Tier 1, not a stretch goal):**
- A lightweight PWA report form (part of the Next.js app, no native app needed for MVP): geolocation + road-status selector (clear / slow / blocked) + optional photo + optional note.
- Each report carries a **reporter trust score** (start neutral, adjust up when reports later correlate with confirmed status — satellite confirmation or corroborating reports — down when contradicted repeatedly). This is what stops the layer from being trivially gameable, and it's a good talking point on its own.
- Fuse reports into the model's belief about an edge's accessibility as a trust-weighted update on top of the ML prediction — start with a simple weighted average for the MVP demo; a proper Bayesian update (each report as a noisy observation with reporter-specific likelihood) is the natural v2.
- WhatsApp/SMS intake is the right real-world channel eventually, but Business API approval overhead is not worth it yet — build the PWA now, name WhatsApp/IVR as the explicit "how this becomes real" roadmap item.

---

## 5. The missing production layer

The Security & Reliability section (§30) is standard SaaS boilerplate — fine as far as it goes, but this is a disaster-logistics tool, and a few things are conspicuously absent:

- **Offline-first / degraded connectivity.** NER terrain means field operators won't reliably have a live connection. Service-worker caching of last-known state and map tiles isn't a UI nicety here — it's the difference between the tool working during the exact events it's meant for, or not.
- **Alerting, not just dashboards.** A tool that only works when someone is actively looking at it is a demo, not a tool. At minimum, a webhook/notification hook for "route reliability crossed a threshold" is worth having even as a stub.
- **A feedback loop.** When an operator overrides a recommendation, or a field report contradicts a model prediction, nothing currently captures that for improvement. Even a simple "log every override with reason" table gets real training signal later, and is a good explainability story — the system visibly learns from operators, not just satellites.
- **Multi-district/state boundaries.** NER is 8 states. Even with Assam as the only validation state, don't hardcode single-tenant assumptions into the schema.

---

## 6. "Why not just use Bhuvan / Sachet?" — have a real answer ready

This deserves a straight answer, stated explicitly.

| Existing system | What it actually does | What it doesn't do |
|---|---|---|
| **Bhuvan** (ISRO/NRSC) | Live spatial flood early-warning system, near-real-time inundation mapping across flood/cyclone/landslide/earthquake/fire | Doesn't touch roads, routing, or resource allocation |
| **Sachet** (NDMA) | CAP-based national alert broadcast over SMS/app/browser | One-way warning; no logistics decision-making |
| **NDEM** (MHA) | National multi-hazard GIS database | A database, not a decision system |
| **ASDMA/NESAC FLEWS** | Assam-specific flood alerts | Same pattern: observe → alert, stops there |

The pattern across all four: **observe → alert.** None of them ask "given what we now know, which route should this truck take, and how confident are we it'll still work when the truck arrives?" That's the actual gap, and it's exactly what the ML-predicts / optimization-decides / scenario-reassesses architecture is built to fill. Put plainly: *existing systems tell you a flood is happening; nothing tells you which road will still work when your truck gets there, or what to do about the one that won't.*

---

## 7. Differentiators — tiered so the MVP doesn't scope-creep

**Tier 1 — bake into the core build, not add-ons**
1. Field-input fusion layer (§4) — also the most direct answer to what the PS text explicitly asks for.
2. Time-aware routing done properly (§2.2) — real technical depth, cheap to explain in the demo.
3. Risk-aware route surfacing — alongside the "best expected reliability" route, also surface the "safest worst-case" route when they diverge (full CVaR-constrained optimization is a stretch goal; showing both options is not).
4. Ferries and river crossings as first-class network edges, not roads-only. Model ferries with their own hazard sensitivity — they don't slow down in high water/current, they stop operating entirely, a different functional relationship than a degrading road.

**Tier 2 — strong, build after the vertical slice works**
5. Historical disaster replay / backtesting mode (§8) — doubles as the required evaluation harness (§24) and is excellent demo material.
6. Pluggable hazard-module architecture (§3) — turns "extensible" from a claim into a fact.
7. Commodity-aware demand decay curves (§2.4).
8. Plain-language explanation generation on top of SHAP/feature importance — "this route dropped from 83% to 41% because the approach road to X bridge entered the newly expanded flood polygon, and the Y gauge rose 1.2m in 6 hours" reads better in a 5-minute demo than a bar chart.

**Tier 3 — the "this could actually ship" layer**
9. A public, read-only accessibility API / embeddable widget — lets NGOs, other apps, or a future consumer map product query "is this road passable right now." Turns the story from "we built a dashboard" into "we built civic infrastructure."
10. Offline-first PWA for field operators (§5).
11. Feedback loop / active learning from overrides and field reports (§5).

---

## 8. Candidate first vertical slice: the Barak Valley corridor

§26 correctly says start with one Assam corridor, but doesn't name one. Worth considering: **Silchar/Cachar ↔ the rest of Assam, via the Dima Hasao (Haflong) and Meghalaya (NH-6) routes.**

This isn't an arbitrary pick — it's a real, recurring, well-documented single point of failure:
- **June 2022:** a Barak River dyke breach at Bethukandi (later ruled deliberate sabotage, with arrests made) submerged Silchar and cut road connectivity to the district; the wider event affected 5.4 million people across 32 NER districts and killed 200+. An on-ground engineer reported the breach by radio before it showed up anywhere else — exactly the field-report-beats-sensor moment the fusion layer (§4) is built for.
- **2024:** Cyclone Remal's aftermath flooded Silchar again and severed rail links to the valley.
- **2025:** a rebuilt section of the Silchar-Kalain highway collapsed, cutting the valley off again while the main NH-6 alternate was already closed for repairs.
- **Recurring:** the Sonapur tunnel on NH-6 through Meghalaya — the same lifeline route — has been blocked by landslides multiple times, cutting off Tripura, Mizoram, and Barak Valley together, not just Assam.

One corridor, three real recurring failure modes (flood, bridge collapse, landslide), and modeling it well has impact beyond Assam — three other states' essential-goods flow depends on the same chokepoint. This also gives a genuine historical-replay dataset (§7, Tier 2) without waiting on live pipelines: 2022/2024/2025 can be reconstructed as backtests from public reporting while live ingestion is still being built.

Treat this as a strong candidate, not a lock — confirm actual CWC/ASDMA gauge coverage near Cachar/Dima Hasao before committing (see §1's access caveats).

---

## 9. What changes in the architecture (delta from v2.0 §4)

```
OBSERVED DATA
  CWC/NWDP (scraper, not API) • ASDMA/NESAC bulletins • Sentinel-1 • OSM • DEM
  • Population • Facilities • FIELD REPORTS (new)
        |
INGESTION / VALIDATION / PROVENANCE   (+ document-parsing path, + staleness flags)
        |
POSTGRESQL + POSTGIS + OBJECT STORAGE
        |
GEOSPATIAL + HAZARD FEATURE ENGINE  -->  HAZARD MODULE REGISTRY (new, pluggable per hazard type)
        |
DYNAMIC ROAD GRAPH   (+ ferry/multimodal edges, new)
        |
GROUND-TRUTH FUSION LAYER (new -- trust-weighted field reports + model prediction)
        |
ACCESSIBILITY FORECASTING   (multi-horizon output, not single point estimate)
        |
DEMAND ESTIMATION   (+ commodity-specific decay)
        |
LOGISTICS OPTIMIZATION   (+ risk-aware / dual-route surfacing)
        |
SCENARIO / WHAT-IF ENGINE   (+ HISTORICAL REPLAY MODE, new)
        |
EXPLANATION + AUDIT TRAIL   (+ plain-language generation, + override feedback log)
        |
FASTAPI API   (+ public read-only accessibility endpoint, new)
        |
NEXT.JS + MAPLIBRE / DECK.GL   (+ offline-first PWA shell, + field-report intake, new)
        |
ALERTING / NOTIFICATION HOOK (new)
```

---

## 10. Open decisions before Day 1

- [ ] Lock the study corridor (Barak Valley candidate above, or an alternative) — needs data-coverage confirmation
- [ ] Formally define the accessibility state type (§2.1) before the first DB migration
- [ ] Decide MVP scope for time-aware routing (§2.2) — at minimum, multi-horizon forecast + 2–3-pass fixed point
- [ ] Confirm CWC/India-WRIS and ASDMA data access with a throwaway script, not an assumption
- [ ] Decide field-report intake channel for MVP (PWA form) vs. roadmap (WhatsApp/SMS)
- [ ] Repo scaffold + first commit

---

### Sources checked (Aug 2026)
- India-WRIS / CWC — indiawris.gov.in, nwdp.nwic.gov.in, PIB press release on India-WRIS relaunch, GUARDIAN framework paper (*Scientific Data*, 2024)
- ASDMA — asdma.assam.gov.in (Flood Alerts, Flood Reports, NRSC hazard-mapping project page)
- Bhuvan / NRSC — bhuvan.nrsc.gov.in (Spatial Flood Early Warning System, Disaster Services)
- Sachet / NDMA — sachet.ndma.gov.in
- Community-based flood EWS (Singora/Jiadhal) — UNFCCC/ICIMOD case study
- 2022/2024/2025 Barak Valley flood reporting — Scroll.in, Eastern Mirror, Assam Tribune, Deccan Herald, Wikipedia (2022 Silchar Floods)

*Compiled August 2026, before any code was written.*
