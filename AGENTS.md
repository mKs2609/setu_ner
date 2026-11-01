# AGENTS.md

Context for AI coding agents working in this repository.

SetuNER forecasts which roads in the Barak Valley corridor of Assam will still
be passable tomorrow, and plans relief deliveries over the ones that survive.
It is a deployed system with a daily job, not a notebook.

---

## The one rule that matters most

**Never make a number look better than it is.**

This project's entire claim is that its figures can be trusted. Several of its
best decisions are places where it reports a loss:

- The 3-day model lost to its baseline on validation, so **the baseline is what
  runs**, and the website says so.
- A rainfall model won on the held-out test but lost on the validation
  criterion fixed in advance, so it is **frozen as a challenger, not served**.
- Live skill is **negative** and published on the forecast page.

If you find yourself rounding toward a nicer figure, softening "it lost" into
"comparable", or quoting the most flattering reading in a series — stop. Report
the number and the caveat together. A result that only shows wins is a sales
document.

Live figures move daily. **Read them from `/api/v1/model/status` before writing
them anywhere**, and date them ("as of 1 Nov 2026") so the next reader re-checks
rather than quotes.

---

## Layout

```
apps/api/            FastAPI service (Python 3.12)
  app/routers/       10 routers, 31 endpoints
  app/services/
    ingestion/       DRIMS scraper: polite client, parsers, run log, catch-up
    weather/         NASA GPM IMERG over OPeNDAP
    model/           Dataset rules, training, scoring, shadow test, calibration
    routing/         Exposure-weighted Dijkstra over a cached sparse matrix
    logistics/       Demand, and the OR-Tools lexicographic planner
    explain/         Per-feature attribution, narratives, audit
    scenario/        What-if engine
  app/db/            SQLAlchemy + GeoAlchemy2 models, session, migration runner
  tests/             319 pytest

apps/web/            Next.js 14 App Router (TypeScript, Tailwind)
  app/               8 pages
  components/        Grouped by domain: map, logistics, scenario, model, …
  lib/api.ts         Every API call. Holds the retry and error-hint helpers
  tests/             28 vitest

geo/                 One-off builders: road graph, terrain, gazetteer, rainfall
ml/models/           Trained artifacts — JSON, versioned, never pickle
infra/migrations/    Idempotent SQL, applied on boot
scripts/monitoring/  The deployment watcher + its 33 standalone checks
docs/decisions/      18 numbered decision records — read these first
```

**The frontend holds no business logic.** No thresholds, no model, no demand
rates. It asks the API and renders what comes back, with the caveats the API
attaches. If you are about to compute a domain figure in `apps/web`, it belongs
in the API instead.

---

## Commands

```bash
# API
cd apps/api && python -m pytest -q              # 319 tests
cd apps/api && uvicorn app.main:app --reload    # serves on :8000

# Web
cd apps/web && pnpm test                        # 28 vitest
cd apps/web && pnpm lint && pnpm type-check
cd apps/web && pnpm build

# Monitoring (stdlib only, no pytest)
python scripts/monitoring/test_check_deployment.py
python scripts/monitoring/check_deployment.py   # runs against production

# Handbook (gitignored; source of truth is docs/handbook/parts/*.html)
python docs/handbook/build.py
```

**Stop any dev server before running `pnpm build`.** Building while `next dev`
holds `.next` has produced a completely unstyled page before now.

---

## Conventions

**Comments explain *why*, never *what*.** Prefer the reason a thing is strange
over a restatement of the code. If a line looks wrong but is deliberate, say
what would break without it.

**Tests assert on behaviour that could silently regress**, not on coverage.
Several suites assert on *printed text* rather than exit codes, because two real
bugs produced the correct exit code and the wrong explanation. If a bug's
symptom was wording, the test must read the wording.

**Decision records** live in `docs/decisions/`, numbered and never deleted. A
superseded one gets a note pointing at its replacement. Records that document a
failure are kept for the same reason as the ones that worked.

**Git**: subject-line only, no body, no `Co-Authored-By` trailer. Write what
changed and why in the subject, in plain English. The repository owner pushes;
suggest the commands, do not run `git push`.

---

## Constraints that are not negotiable

**Secrets.** `DATABASE_URL`, Earthdata credentials and operator token hashes are
platform secrets, never committed, never printed. Only the SHA-256 hash of an
operator token reaches the server. Do not echo a secret into chat or a log.

**Imagery.** NASA (public domain) and OpenStreetMap/CARTO with attribution,
only. No stock photography anywhere, ever.

**Writes are never retried automatically.** A repeated GET costs a second; a
repeated POST files a duplicate field report or saves a second plan into the
audit trail. `retryingFetch` enforces this — do not loosen it.

**Ingestion only ever inserts.** A source going down must show as rising
staleness plus a failed run, never as an empty map that could read as
"all clear". Absence must never look like safety.

**Readiness reports staleness but never fails on it.** Render gates traffic on
`/health/ready`, and no restart makes an old government report appear. The
`stale` flags exist for monitoring to read.

---

## Traps this repository has already fallen into

Each of these shipped, was caught in production, and has a test now. They
repeat in new code if you are not watching for them.

**A category wide enough to hold two causes gets treated as the more
comfortable one.** This has bitten three times:

| Status | Quietly meant two things |
|---|---|
| `no_data` | "the source has nothing" *and* "not published yet" — cost a permanent day of rainfall |
| supersede rule | any later success covered an earlier failure — hid a real failure for a different day |
| `failed` | "unreachable" *and* "answered with the wrong document" — retried something no retry could fix |

When several observations collapse into one, ask which the collapse may throw
away. When a status covers two situations, ask whether they want the same
response — "retry tomorrow" and "a person must look" are not the same response.

**`flex-1` sets `flex-basis: 0%`, which beats `height` in a column flex
container.** `h-[60vh] flex-1` silently collapsed a map to zero on phones, and
its absolutely-positioned legend then drew over the sidebar text. Use
`md:flex-1` so it only applies once the container is a row.

**Developer-facing text reaching production.** The live site told visitors to
check "port 8000". Error copy must branch on whether the API base is local.

**Wrong-but-plausible data.** NASA's OPeNDAP ASCII response labels each row with
its coordinate; parsing it as a plain matrix would have produced a transposed
grid with no error anywhere. Alignment is verified against what was requested.
The same instinct is why every government report is checked against the date
printed inside it.

---

## What is deliberately not here

- **Sentinel-1 flood extent** — needs a real SAR pipeline; a plausible-looking
  one would be worse than none.
- **Rainfall in the served model** — see `docs/decisions/0014` and `0015`.
- **Fitted per-road terrain exposure** — ~25 geolocated damage points is far too
  few. It is a stated assumption, labelled as one everywhere it appears.
- **Depot stock and fleet figures** — no source publishes them. The defaults are
  examples and every response says so.

Do not implement these to "complete" the project. Each is absent for a reason
recorded in `docs/decisions/`.
