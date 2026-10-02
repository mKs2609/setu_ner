# 0016 — Alerting on a Stale Deployment

**Status:** RUNNING from 27 Sep 2026. Twice daily, by scheduled workflow.

## Why

`0013` shipped `/health/ready` with ten checks, including freshness per feed,
and `0008` made a failed ingestion run visible in the run log rather than
silent. Both were about making failure *observable*. Neither made anyone
*observe* it, and the README said so: "a failed run is visible in the API and
the logs, but nothing pages anyone."

The failure that matters here is not a crash. A crash is loud. It is the quiet
one:

- the machine in India that runs ingestion is off, or asleep, or its power
  settings changed;
- an Earthdata credential expires and rainfall stops arriving;
- ASDMA changes the report template and the parser correctly refuses it.

In all three, **nothing fails, because nothing runs.** Staleness climbs while
every page still renders perfectly, and the numbers on them are last week's.
That is precisely the failure mode this project has designed against
everywhere else — absence must never look like safety — left unguarded at the
one layer that could notice.

There is also a deadline. The post-season retrain (`docs/retraining.md`) trains
on the 2026 season. Ingestion breaking quietly in October and being found in
November leaves a hole in the data the retrain depends on, and catch-up only
reaches back 14 days.

## What runs

`scripts/monitoring/check_deployment.py` asks three questions and exits 0 only
if all three are satisfied:

| | Question | Source |
|---|---|---|
| 1 | Can the service serve at all? | `ready` and the ten checks |
| 2 | Is any feed older than its threshold? | the `stale` flags in the same response |
| 3 | Did ingestion run, and finish? | `/api/v1/hazards/freshness` run log |

| Exit | Meaning |
|---|---|
| 0 | healthy: serving, nothing stale, ingestion running |
| 1 | a problem, named — not ready, or stale, or a bad run |
| 2 | no readiness answer at all, after four attempts |

`.github/workflows/watch-deployment.yml` runs it four times a day and on
demand. Standard library only, so the job is a checkout and two requests.

### Question 2 is the one that is easy to get wrong

Readiness reports staleness and **deliberately does not fail on it**. Its own
docstring says why, and `render.yaml` is the reason: `healthCheckPath` points
at that endpoint, so failing it over old data would have Render pull a working
service out of rotation for a problem no restart can fix. The endpoint says as
much — "surfaced here so monitoring can alert on it".

The first version of this watcher only read `ready`, which meant it would have
stayed green through exactly the outage it was built for. Readiness hands
monitoring the signal; monitoring has to actually read it.

### Question 3 catches what readiness cannot see

`ingest_runs` rows are written *before* a fetch and updated when it ends
(`0008`), so a killed or hung job survives as `running` rather than vanishing.
Nothing was looking at that either. A run still `running` after three hours is
reported, as is any failure in the last 36 hours. `no_data` is not reported: a
day with no landslide anywhere is a correct answer, and alerting on it would
teach the reader to ignore alerts.

Nothing ever closes a row left at `running` -- the scheduler treats that day
as still owed and inserts a *new* run for it
(`services/ingestion/schedule.py`). The data therefore recovers by itself,
which shapes when a problem stops being one:

- **Superseded.** A later `success` or `no_data` on the same feed clears it.
  That is the real signal that the incident is over, and it arrives as soon as
  the next run lands rather than on a timer.
- **Aged out.** Failing that, both reports stop after 36 hours.

Without the first rule a single killed job would email every few hours for a
day and a half after it had already been recovered — and an alert that keeps
firing about something already fixed is one the reader learns to delete
unread. The alert exists to say the machine still has a problem, not to
recount one it already got over.

### Superseded means *that day*, not that feed

Corrected 3 Oct 2026, by a real failure the rule had hidden. Catch-up works
newest day first, so one job wrote both of these four seconds apart:

    02:00:43  rainfall  target 2026-10-01  failed
    02:00:47  rainfall  target 2026-09-30  success

The rule compared only (source, hazard), saw a later success on the same
feed, and suppressed the failure. But those are different days: 1 October's
rainfall was still missing, and the watcher stayed green through it.

The key is now (source, hazard, **target day**). A day is only recovered by a
run for that day. A run with no target day is never treated as superseded,
because reporting something already fixed is a smaller mistake than silently
dropping something that is not.

The failure it had been hiding, for the record, was a month boundary: at
02:00 UTC on 2 October NASA had not yet created
`GPM_3IMERGDL.07/2026/10/`, so the fetch 404ed. The directory existed later
the same day and catch-up re-owed the day. Self-healing, but it should have
been visible while it lasted.

### A stale feed is not always a fault

Added 2 Oct 2026, after the first October run made the gap obvious. ASDMA
published nothing on 30 September; ingestion reached the portal, was told
there was nothing, and recorded `no_data`. Entirely correct — and three days
later the flood feed would have crossed the staleness line and started
emailing four times a day about a pipeline that was working.

Outside the monsoon that silence lasts **months**. An alert that fires
through all of it is one its reader learns to delete, including the time it
matters.

So staleness now has to answer one more question before it may fail the
check: **did we stop asking, or did they stop answering?** The run log knows,
because `no_data` means the fetch succeeded and the source had nothing to
give.

| Situation | Verdict |
|---|---|
| Stale, and a feed answered within 36 hours | **Quiet, not broken** — reported as a note, exit 0 |
| Stale, and nothing answered in 36 hours | Ours. Alert |
| Stale beyond 14 days, even with answers | Alert anyway — see below |
| One feed quiet, another stale | Only the quiet one is excused |

The 14-day cap matters. A feed silent that long is indistinguishable from one
whose URL moved and now returns a page the parser correctly refuses — which
is exactly what `no_data` reports. Past that point a person should look, so
the alert comes back rather than suppressing itself forever.

The quiet case is never silent, either: it prints as a `note` line and the
headline says so, so the run page shows the real state even though nothing
failed.

## The alert is the workflow failing

GitHub emails the repository owner when a scheduled workflow fails. That is
the whole notification path: no third-party service, no webhook URL, no
secret to rotate, nothing else to keep alive. The run page carries a summary
naming the checks that failed, so the email links straight to the answer.

A dedicated alerting service would be better at this. It would also be one
more account, one more credential, and one more thing that can quietly stop
working — which is the exact failure being guarded against.

## Two decisions inside it

**It runs on GitHub, not on the ingestion machine.** "That machine is off" is
one of the conditions being reported, so a watcher living there would be off
at the moment it was needed. This is safe to run outside India because it only
calls this project's own API — the portal restriction in `app/jobs/daily.py`
does not apply.

**A cold start is not an outage.** The API is on a free instance that sleeps,
and the first request after a quiet spell can take most of a minute. So a
refused or slow connection is retried patiently, four times with backoff. What
is *not* retried is a readiness response that arrives and says no: 503 with a
body is a real verdict, and asking again would only delay the alert. The
distinction is tested against fake servers returning each case.

## What this is not

It is email, twice a day, to one person. It is not paging, it has no
escalation, and a failure at 09:05 IST waits until 21:00 for its second look.
For a project operated by one person that is the right size; an agency
adopting this would put real monitoring in front of it. The README says so
under Limitations rather than implying more.

## Known wrinkle

GitHub disables scheduled workflows in repositories with no activity for 60
days. If the alerts go quiet, that is the first thing to check — the Actions
tab will say so, and re-enabling is one button.

The scheduler is also best-effort and shared. The first scheduled run here was
queued for 03:30 UTC and started at 09:26 UTC, and GitHub documents that runs
can be dropped under load. Hence four slots a day: not because the data moves
that fast, but so one late or missing slot does not hide a broken pipeline
until tomorrow.
