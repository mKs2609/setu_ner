# Deploying SetuNER

Three pieces, each on the host that suits it:

| Piece | Recommended | Why |
|---|---|---|
| Database | **Neon** or **Supabase** (Postgres 16 + PostGIS) | Managed, PostGIS supported, 187 MB fits free tiers |
| API + daily job | **Railway** (or Render / Fly.io) | Runs the Docker image; needs ~1 GB RAM, which serverless does not give |
| Web | **Vercel** | Built for Next.js |

Pick a **Singapore / South-East Asia** region for all three where offered —
the users and the data sources are in Assam.

> Platform dashboards change. The settings named below are what each needs to
> be told; where a label differs, look for its equivalent.

Everything below was rehearsed locally except the hosted steps themselves:
the export, the migrations runner, the image recipe (built in CI), token
enforcement and the daily job.

### Free path (no card)

| Piece | Free host |
|---|---|
| Database | **Neon** free tier |
| API | **Hugging Face Docker Space** — free CPU tier, 16 GB RAM; sleeps after 48 h without visits and takes a minute or two to wake |
| Daily job | **GitHub Actions** scheduled workflow (`.github/workflows/daily-job.yml`) — free for a public repo |
| Web | **Vercel** free tier |

Render's free web tier (512 MB) is not recommended: the road graph alone uses
~240 MB and planning adds more. Steps 2 and 3 below have free-path variants.

---

## 0. Before you start

**Export the data** (roads, terrain, 313 days of reports, model forecasts).
From the repo root, with the local database running:

```powershell
$env:PGPASSWORD = "sih26002"
.\scripts\deploy\export_data.ps1
```

This writes `data\deploy\setuner.dump` (~21 MB). It leaves out rows from
`field_reports`, `reporters`, `recommendations` and `recommendation_overrides`
— local test data should not appear as real operator activity. `data/` and
`*.dump` are gitignored.

**Generate an operator token** for each person who will save plans, record
overrides or (by default) submit field reports:

```bash
cd apps/api
python -m app.security new-token
```

Give the **token** to the operator privately. Put only the **hash** on the
server. Revoke someone by removing their hash.

---

## 1. Database

1. Create a Postgres 16 project in a Singapore region.
2. Copy the **direct** (non-pooled) connection string, with `?sslmode=require`.
   Pooled connections can break `pg_restore`.
3. Load the dump. The archive includes `CREATE EXTENSION IF NOT EXISTS postgis`:

   ```powershell
   & "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" --no-owner --no-acl --exit-on-error `
     --dbname "postgresql://USER:PASSWORD@HOST/DB?sslmode=require" data\deploy\setuner.dump
   ```

4. Confirm the schema is current (the dump carries the migration ledger, so
   this should report nothing to do):

   ```bash
   cd apps/api
   DATABASE_URL="postgresql://...?sslmode=require" python -m app.db.migrate --status
   ```

   Starting from an **empty** database instead of the dump? `python -m
   app.db.migrate` builds the full schema, but the corridor then has no roads
   and the scripts in `geo/` would need re-running — avoid that.

---

## 2. API

Deploy from the GitHub repo as a **Docker** service.

| Setting | Value |
|---|---|
| Build context / root directory | the **repo root** (not `apps/api`) |
| Dockerfile path | `apps/api/Dockerfile` |
| Memory | **1 GB** (the road graph alone is ~240 MB; planning adds to it) |
| Instances | 1 to start; scale instances, not workers |
| Health check path | `/api/v1/health/ready` |

Environment variables:

| Name | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | the connection string from step 1 |
| `CORS_ALLOWED_ORIGINS` | `["https://your-app.vercel.app"]` |
| `OPERATOR_TOKEN_HASHES` | `["<hash>", "<hash>"]` |
| `PUBLIC_FIELD_REPORTS` | `false` (set `true` only for open crowdsourcing) |

`PORT` is read from the platform. **The API refuses to start** if the token
list is empty, CORS includes localhost or `*`, or `DATABASE_URL` is the local
default — check the deploy log for `Refusing to start in production` and the
list of reasons.

Verify:

```bash
curl https://YOUR-API/api/v1/health/ready
```

`"ready": true` with every check `ok`. `data_freshness` will show the age of
the newest report — it goes stale until step 3 runs.

### 2 (free path). API on a Hugging Face Space

1. Create a free account at huggingface.co, then **New Space**: SDK **Docker**,
   template **Blank**, hardware **CPU basic (free)**, visibility public or
   private.
2. Upload the two files from `deploy/huggingface/` in this repo
   (`Dockerfile`, `README.md`) to the Space (Files -> Add file -> Upload).
   The Dockerfile clones this GitHub repo at build time, so nothing else is
   needed in the Space.
3. Space **Settings -> Variables and secrets**, add as **secrets**:
   `ENVIRONMENT=production`, `DATABASE_URL` (Neon *pooled* string),
   `CORS_ALLOWED_ORIGINS=["https://your-app.vercel.app"]`,
   `OPERATOR_TOKEN_HASHES=["<hash>"]`, `PUBLIC_FIELD_REPORTS=false`.
4. The Space builds and starts. Its API is at
   `https://<username>-<space-name>.hf.space`; check `/api/v1/health/ready`.
5. After new commits to `master`, use **Settings -> Restart / rebuild** to pick
   them up.

---

## 3. Daily job

A second service from the **same repo and Dockerfile**, run on a schedule:

| Setting | Value |
|---|---|
| Start command | `python -m app.jobs.daily` |
| Schedule | `30 20 * * *` (02:00 IST — DRIMS publishes late in the day) |
| Environment | the same `DATABASE_URL` and `ENVIRONMENT` as the API |

It runs flood and landslide catch-up, damage matching and scoring, then exits.
A non-zero exit means a step failed — including the scorer refusing a report
older than three days — so point the platform's failed-job alert at it.

**Free path:** the workflow `.github/workflows/daily-job.yml` runs the same
command on GitHub's scheduler at the same time. Add one repository secret,
`DATABASE_URL` (GitHub repo -> Settings -> Secrets and variables -> Actions ->
New repository secret), then run it once by hand from the Actions tab
("Daily job" -> Run workflow). Without the secret it skips instead of failing.
GitHub pauses schedules in repos with no activity for 60 days.

The job fetches from the ASDMA portal through the polite client (robots.txt,
crawl delay, identified user agent). Do not schedule it more than once a day.

---

## 4. Web

Import the repo into Vercel:

| Setting | Value |
|---|---|
| Root directory | `apps/web` |
| Framework | Next.js |
| `NEXT_PUBLIC_API_URL` | `https://YOUR-API` (no trailing slash) |

Then make sure the API's `CORS_ALLOWED_ORIGINS` has the exact Vercel URL, and
redeploy the API if you changed it.

---

## 5. Check it end to end

1. `/accessibility` — forecasts load; "Why?" opens; clicking a road explains it.
2. `/logistics` — pick a report day, build a plan without saving (no token
   needed).
3. Tick **Save this plan as a record** — it should ask for a token; enter one;
   save succeeds and links to the record.
4. On the record, add an override — same token.
5. `/api/v1/model/status` — artifacts present, scoring as-of recent.

---

## Operating it

- **Token hygiene.** One token per operator. Tokens live in the browser tab's
  session storage and vanish when the tab closes.
- **Monitoring.** Point an uptime check at `/api/v1/health/ready` and alert on
  `data_freshness.stale` — a dead daily job looks healthy otherwise.
- **Backups.** Enable the database provider's point-in-time recovery. The
  audit trail (`recommendations`, `recommendation_overrides`) cannot be
  regenerated.
- **Retraining** after a monsoon season: run `python -m app.services.model.train`
  locally against a copy of production data, commit the new artifacts, and
  redeploy — the image carries them.
- **Schema changes**: add `infra/migrations/NNNN_*.sql` (with IF NOT EXISTS),
  then run `python -m app.db.migrate` against production before deploying code
  that depends on it.

## What this does not provide

- **User accounts.** Operator tokens say "an authorised operator", not who.
  Agency adoption needs SSO and roles in front of the API.
- **Edge rate limiting.** In-app limits exist (plans, saves, overrides, field
  reports); a public launch should add the platform's or a CDN's as well.
- **High availability.** One API instance and one job. Fine for a pilot.
