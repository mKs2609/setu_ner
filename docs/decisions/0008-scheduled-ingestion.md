# 0008 — Scheduled Ingestion, and Reaching Current Conditions From the UI

**Status:** BUILT — 11 Sep 2026.

## Why scheduling was the gap worth closing

The system's whole claim rests on live conditions, and the data only moved
when somebody remembered to type a command. On starting this, the newest
DRIMS report in the database was three days old — not because the source was
down, but because nobody had run the script. `/hazards/freshness` reported
that decay honestly while nothing acted on it.

It is also the only thing that will unblock Phase 3. That remains stuck on
**3 labelled road-days**, and no amount of modelling effort changes it. Only
accumulated history does, and history accumulates on a schedule.

## Catch-up, not "fetch yesterday"

A daily job that only ever asks for yesterday has a quiet failure mode: miss
a week and that week is gone permanently, because tomorrow's run only asks
for tomorrow. Freshness would show the data recovering while a hole sat in
the history behind it.

So the scheduled job asks a different question — *what have we not got yet?*

| Recorded status | Behaviour | Why |
|---|---|---|
| `success` | Never re-fetched | Idempotent, so harmless, but pointless traffic against a government site |
| `failed` | Always retried | Our problem — a timeout or parse error — and the report may still be there |
| `no_data` | Retried only within 3 days | "No report published" is a real answer, but districts submit late |
| `running` | Retried | Almost always a killed process; treating it as done loses the day |
| never run | Fetched | |

Newest-first, and capped at 14 days per invocation, so a first run against an
empty database cannot decide it owes a year and hammer the source in one go.
When the cap bites, the run says so rather than hiding the remaining gap.

The rule is a pure function (`plan_catch_up`) with 15 tests and no database
or network, because its failure mode is a silent hole in history rather than
an error anybody would see.

## Verified on real data

Catch-up found and filled genuine gaps: **09-10 had never run** and 09-09 was
`no_data`. It fetched those plus older missing days, skipping everything
already ingested.

| | Before | After |
|---|---|---|
| Hazard observations | 692 | **1,980** |
| Days of history | 20 | **34** |
| Geolocated damage points | 33 | **42** |
| Gaps in the last 20 days | 4 | **0** |

## How it is scheduled

`scripts/scheduling/` holds a PowerShell wrapper for Windows Task Scheduler,
and `scripts/scheduling/README.md` documents cron and Docker equivalents. A
`docker-compose` `ingestion` service exists behind a `scheduling` profile, so
a normal `docker compose up` does not start it — hitting a government portal
should be a deliberate choice, not a side effect of bringing the stack up.

Three settings matter more than the schedule itself:

- **`-StartWhenAvailable`** — a laptop asleep at 07:30 runs the missed
  trigger when it wakes rather than skipping the day.
- **`-MultipleInstances IgnoreNew`** — a slow catch-up must not overlap the
  next run. Idempotency means an overlap could not corrupt anything, but two
  runs hitting the portal at once defeats the crawl delay.
- **`-ExecutionTimeLimit`** — a hung run is killed rather than leaving a
  `running` row forever. Catch-up then treats that day as still owed.

07:30 is chosen: the report quotes the CWC bulletin issued at 8 AM IST and is
compiled from district submissions through the day, so the run targets
yesterday, which is settled by then.

Hazards run in sequence, never in parallel — the polite client enforces a
crawl delay per host and concurrency would sidestep it.

## The UI half

`0007` built current-conditions routing with no way to reach it from the app.
A backend capability nobody can invoke is not finished, so `/scenarios` now
has a **Clean network / Conditions now** toggle, and a result panel showing
exactly what the live layers applied before the scenario ran — each road, its
effect, and the reason.

## The overstatement this surfaced, again

The verdict chip read **CUT OFF** above a sentence saying *"this is a local
blockage, not the corridor being severed."* Same overstatement `0007` fixed
in the prose, just moved up the screen where it is read first.

`RouteResult.as_dict()` now exposes the diagnosis `kind`, and the chip labels
it accordingly: **Cannot set out** / **Cannot arrive** / **Both ends
isolated** / **Cut off**. "Cut off" is reserved for genuine severance.

Worth noting the pattern: this is the second time the honest text existed
while a more prominent element contradicted it. A caveat only works if it is
at least as visible as the claim it qualifies.

## Honest limitations

- **No alerting.** A failed run is recorded and visible in
  `/hazards/freshness`, but nothing pages anybody. For a tool meant to be
  used during a disaster this is a real gap, and `0001` section 5 already
  named it. Wiring freshness to a webhook is the obvious next step.
- **The schedule is not registered on this machine.** The scripts and
  instructions exist; running `Register-ScheduledTask` is a deliberate act
  left to whoever owns the machine.
- **Catch-up depends on `ingest_runs` being accurate.** A day whose run row
  was lost looks like a day never attempted, and gets re-fetched. Harmless,
  but it means the table is load-bearing.
- **Nothing prunes old logs.** `logs/ingestion-YYYY-MM.log` grows monthly.

## Testing

17 new tests, 130 in the suite. The catch-up planner is tested exhaustively
without a database — settled days, retried days, the late-submission
boundary, mid-history gaps, and truncation reporting.

## Next

Phase 3 is now a waiting game rather than a blocked one: with the schedule
running, history accumulates on its own. The remaining input it needs is
labels, which means real reporters on the field-report screen.

The pitch deck's three overflow slides are still outstanding.

## The day that was quietly written off (13 October 2026)

NASA's OPeNDAP service returned 500 for three days. Catch-up handled it the
way it was meant to — kept asking, recovered 10 and 11 October as soon as the
service came back — but **9 October was never refetched, and is a permanent
hole in the rainfall series.**

The cause is the interaction of two rules that are each correct alone:

- `existing_run_status` recorded the *best* outcome per day, so a success
  after two failures correctly means the day is held.
- `plan_catch_up` stops retrying a `no_data` day after three days, because a
  day the source genuinely has nothing for should not be asked about forever.

9 October was first asked for before IMERG had published it, which is the
normal lag and is recorded as `no_data`. It then failed twice against the
outage. Best-of made the day read as `no_data`, the three-day cap wrote it
off, and nothing ever said so.

The flaw is that `no_data` means two different things depending on when it
was recorded: "the source has nothing for this day" and "not published yet".
Only the first justifies giving up. Taking the best of all attempts throws
away the evidence that distinguishes them.

`success` still settles a day outright. For every other outcome the **most
recent** attempt now governs, because a later failure is newer information
than an earlier `no_data`, and the newer statement is the true one.

This is the same shape as the supersede bug in [0016](0016-alerting.md): an
optimistic aggregate hiding a pessimistic fact. Worth remembering as a
pattern — when several observations of the same thing are collapsed into one,
ask which of them the collapse is allowed to discard.

The fix also repairs the existing hole without intervention: 9 October now
reads as `failed`, so it is owed again and the next successful run fetches it.

## When the source answers, and the answer is wrong (20 October 2026)

From 16 October, ASDMA served the flood report printed **2025-05-16** whenever
we asked for **2026-10-16** — seventeen months stale, same day of the month,
which smells like a lookup fault in their archive. The landslide report for
that date was correct, and every other date was correct. Reproducible on
demand, and still reproducible four days later.

The date guard refused it, which is the whole point of comparing the date
printed inside the document against the date requested. Without it the system
would have filed May 2025 flood conditions under 16 October 2026: a map of
last year's floods presented as today's, with nothing anywhere to say so.

But it was **recorded as `failed`**, and that was wrong. `failed` means "we
could not get it" and invites a retry — which is correct for the NASA outage,
where patience was the whole answer. Here the retry fetches the identical
wrong document every morning, so the scheduler asked four days running and the
watcher emailed sixteen times about a thing no retry can fix.

Two events, one status:

| | What happened | What helps |
|---|---|---|
| `failed` | We could not reach the source, or it errored | Retry tomorrow |
| `rejected` | We reached it, it answered, the answer was wrong | A person |

A date mismatch is now recorded as **`rejected`**. Catch-up retries such a day
for `REJECTED_RETRY_DAYS` (2) — enough to cover a transient publishing glitch
— and then leaves it alone. The watcher reports it with what it is and what to
do, rather than as a generic failure, and because no new `rejected` run is
created after the window the alert ages out and goes quiet on its own. Nothing
is suppressed; the scheduler simply stops asking a question that has been
answered.

A `rejected` day is **not** settled. It is genuinely missing, and a later
success still wins, so if ASDMA ever fixes that file a manual
`--start 2026-10-16 --end 2026-10-16` collects it — which is the right shape
for something a person should confirm before trusting.

This is the third time one status has carried two meanings in this project:
`no_data` meaning both "nothing happened" and "not published yet", the
supersede rule treating any later success as covering an earlier failure, and
now `failed` meaning both "unreachable" and "answered wrongly". The pattern is
the same each time — **a category wide enough to hold two causes will be
treated as the more comfortable one.** The guard that caught this was written
because the same question was asked of the data: can this document be
something other than what we asked for?
