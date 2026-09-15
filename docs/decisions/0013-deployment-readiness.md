# 0013 — Deployment Readiness

**Status:** BUILT. The project can be deployed safely by following
`docs/deployment.md`. Nothing is deployed yet. 15 Sep 2026.

## The gaps that stood between the code and a public URL

| Gap | Risk if deployed as it was |
|---|---|
| Every write endpoint open | Anyone could close roads in routing with fake field reports, or fill the audit trail with fake plans and overrides |
| API image built from `apps/api` only | Model artifacts, gazetteer and migrations missing: the service boots, passes a liveness probe, and fails every forecast and plan |
| No readiness check | A deploy with no PostGIS, an unapplied migration or an empty database looks healthy |
| No migrations runner | Schema changes applied by hand, differently on each database |
| Data not in git | Roads, terrain and 313 days of history would have to be rebuilt against public services |
| Three schedulers running slightly different steps | The Windows task, Docker loop and any cloud cron drift apart |
| Compose `web` pointed at a Dockerfile that never existed | `docker compose up` failed |
| `data/deploy/` not gitignored | A 21 MB database dump one `git add -A` from being committed |

## What was built

**Operator tokens** (`app/security.py`). Saving a plan, recording an override,
and — in production — submitting a field report need
`Authorization: Bearer <token>`. The server stores only SHA-256 hashes and
compares in constant time; one operator is revoked by removing one hash. Field
reports can be opened to the public with `PUBLIC_FIELD_REPORTS=true`, but that
has to be chosen: a report can close a road. Reading, forecasting and planning
without saving stay public. Verified with a generated token: every write
refused without it or with a wrong one (401), accepted with it, planning
unaffected.

Tokens are not user accounts, deliberately — they identify "an authorised
operator", consistent with the no-personal-data design of field reports.

**The API refuses an unsafe production config** — no token hashes, a raw token
where a hash belongs, localhost or `*` in CORS, the development database URL —
and lists every reason at startup. CORS now allows only the methods and headers
the API uses.

**Readiness** (`/api/v1/health/ready`) checks database, PostGIS, required
tables, migrations, road data, model artifacts and gazetteer, returning 503
with the failing check named. Data freshness is reported but does not fail
readiness: stale forecasts are already marked stale where they are served.

**Planner concurrency limit.** More than `MAX_CONCURRENT_PLANS` (default 2)
simultaneous plans get 429 with `Retry-After`, instead of an out-of-memory
kill that would take every request down with it.

**Image** built from the repo root, including artifacts, gazetteer and
migrations; non-root user; platform `$PORT`; one worker (the graph is cached
per process); container healthcheck. **CI now builds it on every push**,
checks the artifacts are inside, and checks it refuses a production start
without configuration.

**Migrations runner** (`python -m app.db.migrate`): PostGIS extension, then
`create_all`, then each `infra/migrations` file once, recorded in
`schema_migrations`. Applied to the local database; a test fails any
migration that is not safe to re-run.

**Data export** (`scripts/deploy/export_data.ps1`): a 21 MB custom-format dump
without the four tables that hold local test activity. Verified with
`pg_restore --list`: PostGIS extension, all 12 table schemas, data for the 9
real tables including the migration ledger. A full restore into a scratch
database could not be run locally — the local role cannot create databases —
so the first real restore is verified by `/health/ready` after loading.

**One daily job** (`python -m app.jobs.daily`) used by every scheduler. Ran it
end to end: 108 s, exit 0. It also showed landslide ingestion had not run
since 31 Aug on this machine — the Windows task was never registered — which
the catch-up then recovered.

## Recommended hosting

Neon or Supabase for PostGIS, Railway (or Render/Fly) for the API image and a
scheduled job with 1 GB RAM, Vercel for the web app — all in a Singapore
region. Measured: the database is 187 MB; the API holds ~240 MB once the road
graph is loaded. Serverless platforms are ruled out by the graph cache and the
geospatial dependencies.

## Testing

25 new tests, none needing a database or Docker: token acceptance and every
refusal shape, open-in-development versus closed-in-production, each write
endpoint returning 401 before touching the database, the planner's 429, every
production-config problem, migration re-run safety, every file the Dockerfile
copies existing, a non-root image, and dumps being gitignored.

## Not done

- Nothing is deployed; that needs accounts on the chosen hosts.
- No user accounts or roles (see above).
- No edge rate limiting or high availability — appropriate for a pilot, not a
  public launch.
