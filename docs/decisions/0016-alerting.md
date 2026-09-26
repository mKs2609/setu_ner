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

`scripts/monitoring/check_deployment.py` asks `/api/v1/health/ready`, prints
every check, and exits:

| Exit | Meaning |
|---|---|
| 0 | ready, all ten checks passing |
| 1 | answered, and not ready — the failing checks are named |
| 2 | no readiness answer at all, after four attempts |

`.github/workflows/watch-deployment.yml` runs it at 03:30 and 15:30 UTC
(09:00 and 21:00 IST) and on demand. Standard library only, so the job is a
checkout and one request.

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
