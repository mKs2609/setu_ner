# 0004 — Live Hazard Ingestion

**Status:** BUILT — fetching, parsing and storing real live data, verified
end to end on 8 Sep 2026.

## The finding that changed the plan

`0002` committed to ingesting CWC's Daily Flood Situation Report by its
dated URL pattern, and a fetcher was written against it. **That pattern is
dead.**

Checked 8 Sep 2026:

- `cwc.gov.in/en/daily-flood-situation-report-cum-advisory-dated-DDMMYYYY`
  returns **404 for every date across a week**.
- The listing page `cwc.gov.in/en/fmo/dfsra` loads fine, renders its
  "Name of Publication" table header, and has **no rows at all**.

So the script could never have succeeded on any run since the pattern
changed. It was kept in the tree for a while with a header saying so, and
removed once it was clear CWC had not resumed publishing; this record is the
remaining account of the approach, which is still the right one if they do.

Worth noting for the record: the docstrings in `geo/river/` say government
sites are unreachable from the dev sandbox. That is no longer true — cwc.gov.in,
asdma.assam.gov.in and sdrf.assam.gov.in all respond fine now, which is how
the dead pattern was caught.

## The source we moved to

**DRIMS Assam** — the Disaster Reporting and Information Management System,
run by ASDMA at `sdrf.assam.gov.in/dfr`. Found by following an external link
off ASDMA's own flood-report page.

It is better than the CWC plan on every axis that matters:

| | CWC bulletin (planned) | DRIMS (built) |
|---|---|---|
| Availability | Dead — 404s | Live, one report per day |
| Hazards | Flood only | Nine offered; **flood and landslide parsed** (see below) |
| Structure | PDF prose + tables | Per-district tables |
| Road/bridge damage | No | **Yes, per district, with coordinates** |
| River levels | Yes | Yes — it quotes the CWC 8 AM bulletin |
| robots.txt | none published (allow-all) | explicit empty `Disallow:` (allow-all) |

The road, bridge and embankment damage sections are the important part.
They are the closest thing this project has ever had to ground truth about
the infrastructure it actually models, and they come with road name,
location and lat/lon when the reporting district supplies them.

### Offered is not the same as readable

The endpoint serves nine hazard types, and it would be easy to claim nine.
Tested on 8 Sep 2026:

- **flood** — parsed, 55 observations for 2026-09-07.
- **landslide** — same report template, parses correctly. That day had zero
  landslides, so it legitimately yields zero rows.
- **rainfall** — a completely different document (an IMD state-wise
  cumulated bulletin). This parser cannot read it.

Those last two look identical from the outside: a successful download and
zero rows. So `parse_report` also reports whether it recognised the
template, and the runner **fails** an unrecognised one instead of recording
a success. Without that, pointing the job at rainfall would have looked like
a permanently quiet hazard rather than a parser that cannot read the file.

The schema is hazard-agnostic and the source is multi-hazard, so the
architecture in `0001` section 3 is genuinely reachable — but what is
readable today is flood and landslide, and the code says so.

## How the download works

Not a plain file URL. A Laravel form:

1. `GET /dfr/download?type=<hazard>` → form page with a CSRF `_token` and a
   session cookie.
2. `POST /dfr/download` with `_token`, `type`, `date` (YYYY-MM-DD) →
   `application/pdf`, or the HTML form again when that date has no report.

## What was built

- `services/ingestion/http_client.py` — the polite HTTP client.
- `services/ingestion/districts.py` — district name normalisation.
- `services/ingestion/sources/drims.py` — fetch and parse.
- `services/ingestion/store.py` — idempotent persistence + run bookkeeping.
- `services/ingestion/run.py` — CLI entry point.
- `routers/hazards.py` — `GET /hazards` and `GET /hazards/freshness`.
- Tables `hazard_observations` and `ingest_runs`, hazard-agnostic per `0001` §3.

```bash
cd apps/api
python -m app.services.ingestion.run                  # yesterday's flood report
python -m app.services.ingestion.run --hazard landslide
python -m app.services.ingestion.run --backfill 7
```

## Verified on real data (8 Sep 2026)

Ingested the 2026-09-07 flood report: **55 observations parsed and stored**,
covering 6 districts and 10 metrics. Re-running the same day wrote **0 rows
and recorded 55 duplicates** — idempotency working.

Corridor-relevant rows that came back: Cachar reported affected, 1 revenue
circle, 5 villages, 0 population affected, 2 ha crop submerged, 0 roads,
bridges and embankments damaged. Sribhumi rows correctly stored as Karimganj.
One geolocated damage point (a PWD road in Nagaon at 92.742357, 26.380558).

## What makes this safe to run unattended

**1. Never destructive.** Ingestion only inserts. It does not delete, blank
or overwrite earlier observations. A source going down therefore surfaces as
stale data plus a failed run — never as an empty result that reads like "no
flooding anywhere". That is the single most dangerous failure this system
could have, and the schema forecloses it.

**2. Idempotent.** Every observation has a deterministic `observation_key`,
unique in the database. Re-running a day is a no-op, so retries, cron
overlaps and manual re-runs cannot double-count. This is what makes it safe
to schedule.

**3. Staleness is a first-class field.** `observed_at` (when the world was
like this) is stored separately from `fetched_at` (when we pulled it), and
`GET /hazards/freshness` publishes the age and a fresh / stale / very_stale
status against declared thresholds. Every list response also carries the
freshness of what it just returned, so a caller has to ignore the age
deliberately rather than by accident.

**4. Polite by construction.** robots.txt honoured and cached per host;
crawl delay between requests to the same host; retries only on genuinely
transient failures (timeouts, 5xx, 429) with exponential backoff and jitter;
never retries a 4xx, because that is a real answer; timeout on every request;
response size cap; no concurrency against one host; and an honest User-Agent
naming the project and that it is non-commercial. If a source blocks us the
correct response is to stop, not to work around it.

**5. Refuses the wrong day.** The date printed inside the report is compared
with the date we asked for. A mismatch fails the run rather than filing
those numbers under the wrong date — a real risk with a form-driven download.

**6. Parses only what it can defend.** The report has about two dozen
sections; nine are parsed. The rest — relief camp demographics, livestock,
relief distributed, wildlife — have ambiguous columns or need a judgement
call about what the number means, so they are left alone. Every observation
keeps its source row in `raw`, so widening the parser later needs no
re-fetch and a wrong number stays traceable.

## The rename that would have broken everything quietly

Assam renamed **Karimganj to Sribhumi** in 2024. The live feed says Sribhumi.
The road graph, the district polygons and every accessibility score say
Karimganj.

Ingesting the source's spelling verbatim would have produced hazard rows
that join to nothing — the corridor would have looked unaffected during a
flood, with no error anywhere. `districts.py` maps it, keeps the source's
original spelling in `place_name` so the mapping stays auditable, and
returns `None` for districts it cannot justify rather than guessing.

## Honest limitations

- **Coarse in space.** District-level, not per-road. Confidence is recorded
  as `medium` on every row: better than the annual retrospective the baseline
  score uses, weaker than a direct measurement.
- **Daily, not real-time.** One report per day, compiled from district
  submissions. Today's usually is not published until late in the day, which
  is why the runner defaults to yesterday.
- **Self-reported.** These are figures districts submit, with the reporting
  lags and gaps that implies.
- **Damage points are not matched to road segments.** The coordinates are
  stored; joining them to edges in the graph needs a distance threshold and a
  way to say "no confident match", which is its own piece of work.
- **Nothing feeds the accessibility model yet.** `hazard_exposure` and
  `current_accessibility` on the roads table are still empty. Connecting them
  is Phase 3 and deliberately not done here — see below.

## Deliberately not done

Wiring these observations into `current_accessibility` would have been easy
and wrong. A district-level daily count is not a per-road live accessibility
score, and computing one from the other would manufacture exactly the kind of
authoritative-looking number this project has ruled out. The columns stay
empty until there is a real model, and the data now exists to build one
against.

## Next

Accumulate a few weeks of daily reports, then Phase 3: match damage points to
road segments, and use district exposure plus the historical baseline as
features for a model that has something real to be evaluated against.
