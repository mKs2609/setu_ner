"""
Is the deployment actually healthy right now?

    python scripts/monitoring/check_deployment.py
    python scripts/monitoring/check_deployment.py --base http://localhost:8000

Asks the live API's readiness endpoint and prints every check, then exits
non-zero if anything is wrong. Run it by hand, or let the scheduled workflow
in .github/workflows/watch-deployment.yml run it for you (that is the alert:
GitHub emails the repository owner when a scheduled job fails).

WHAT THIS CATCHES THAT NOTHING ELSE DOES
`/health/ready` already reports ten checks, including freshness per feed. The
gap was that nobody was looking. The failure this exists for is the quiet one:
the ingestion machine is off, or a credential expired, so no run fails --
there is simply no run at all, and staleness climbs while every dashboard
still renders yesterday's numbers perfectly.

WHY IT RUNS FROM GITHUB AND NOT THE INGESTION MACHINE
"That PC is off" is the thing being reported, so the watcher cannot live on
that PC. It only ever calls this project's own API, so the India-only
restriction on the ASDMA portal (app/jobs/daily.py) does not apply here.

A STALE FEED IS NOT ALWAYS A FAULT
Before staleness is allowed to fail the check it has to answer one more
question: did we stop asking, or did the source stop answering? The run log
knows the difference -- `no_data` means we reached the portal and it had
nothing to give. Outside the monsoon the Assam flood report stops for
months, and a watcher that emails about that four times a day would train
its reader to delete the emails, including the one that matters.

A COLD START IS NOT AN OUTAGE
The API runs on a free instance that sleeps when idle, and the first request
after a quiet spell can take the better part of a minute. So a slow or
refused connection is retried patiently. What is NOT retried is a readiness
response that arrives and says no: that is a real answer, and repeating the
question would only delay the alert.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_BASE = "https://setuner-api.onrender.com"
READY_PATH = "/api/v1/health/ready"
RUNS_PATH = "/api/v1/hazards/freshness"

# A daily job step times out at 45 minutes and catch-up can run several. Past
# three hours a run is not slow, it is gone: the process was killed, the
# machine slept, or the network dropped mid-fetch.
STUCK_AFTER_HOURS = 3

# Which feed each freshness check is about, so a stale check can be asked
# the follow-up question that decides whether it is anybody's fault.
FEED_FOR_CHECK = {
    "data_freshness": ("drims_assam_daily_report", "flood"),
    "rainfall_freshness": ("nasa_gpm_imerg_late", "rainfall"),
}

# A run that reached the source and got a straight answer -- including "there
# is nothing for that day", which is an answer, not a failure.
ANSWERED = {"success", "no_data"}

# How recently we must have asked before "they are quiet" is a fair reading.
ASKED_WITHIN_HOURS = 36

# ...and how long that reading stays fair. ASDMA stops publishing daily flood
# reports outside the monsoon, which is normal and lasts months -- but a feed
# that has been silent this long is indistinguishable from one whose URL
# moved and now returns a page we correctly refuse to parse. At that point a
# person should look, so the alert comes back.
QUIET_TOLERATED_DAYS = 14

# The run log keeps everything, and nothing ever closes a row left at
# `running` -- the scheduler simply re-owes that day and inserts a new run
# (services/ingestion/schedule.py). So both a hung run and a failed one are
# only worth reporting while they are recent: after this, the data has
# already been recovered by a later run and the row is history, not an alert
# that would fire every day forever.
FAILURE_WINDOW_HOURS = 36

# Generous: a sleeping free instance has to cold-start before it can answer.
TIMEOUT_S = 90
ATTEMPTS = 4
BACKOFF_S = 20

USER_AGENT = "setuner-deployment-check (+https://github.com/mKs2609/setu_ner)"


class Unreachable(Exception):
    """No readiness answer at all, after every attempt."""


def fetch(url: str) -> dict:
    """The readiness body, whether it came back 200 or 503.

    The endpoint answers 503 when it is not ready, which urllib raises as an
    HTTPError -- but that response carries the check detail we came for, so it
    is read rather than discarded.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = ""

    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            # A readiness verdict, even an unhappy one, is a real answer.
            if isinstance(parsed, dict) and "checks" in parsed:
                return parsed
            # 502/504 and friends are the platform, not the app: worth retrying.
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = f"{type(exc).__name__}: {exc}"

        if attempt < ATTEMPTS:
            print(f"  attempt {attempt}/{ATTEMPTS} failed ({last}); waiting {BACKOFF_S}s")
            time.sleep(BACKOFF_S)

    raise Unreachable(last)


def started_at(run: dict) -> datetime | None:
    """When a run began, as an aware datetime, or None if unreadable."""
    try:
        moment = datetime.fromisoformat(str(run.get("started_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def age_hours(iso: str) -> float | None:
    """Hours since an ISO timestamp, or None if it cannot be read."""
    moment = started_at({"started_at": iso})
    if moment is None:
        return None
    return (datetime.now(timezone.utc) - moment).total_seconds() / 3600


SETTLED = {"success", "no_data"}


def superseded(run: dict, runs: list[dict]) -> bool:
    """True when this run's own day has since been fetched successfully.

    Nothing ever rewrites a row left at `running`, and a failed day is simply
    re-owed: the scheduler inserts a *new* run for that day
    (services/ingestion/schedule.py). So a later success or no_data clears
    it, and saying otherwise every few hours until the row ages out would
    teach the reader to ignore the alert.

    THE DAY MATTERS, NOT JUST THE FEED
    This compared only (source, hazard) until 3 Oct 2026, when a real failure
    showed why that is wrong. One catch-up run works newest day first, so a
    single job wrote:

        02:00:43  rainfall  target 2026-10-01  failed
        02:00:47  rainfall  target 2026-09-30  success

    A later success on the same feed -- four seconds later -- hid a failure
    for a different day. The 1 October rainfall was still missing and the
    watcher stayed green. A day is only recovered by a run for *that day*.

    A run with no target day cannot be matched this way, so it is never
    treated as superseded: reporting something already fixed is a smaller
    mistake than silently dropping something that is not.
    """
    when = started_at(run)
    target = run.get("target_date")
    if when is None or target is None:
        return False
    key = (run.get("source"), run.get("hazard_type"), target)
    for other in runs:
        if other is run or other.get("status") not in SETTLED:
            continue
        if (other.get("source"), other.get("hazard_type"), other.get("target_date")) != key:
            continue
        later = started_at(other)
        if later is not None and later > when:
            return True
    return False


def asked_recently(runs: list[dict], source: str, hazard: str) -> float | None:
    """Hours since this feed last gave a straight answer, or None if it has not.

    `no_data` counts. A day the government did not publish is a successful
    conversation with the source, not a failed one -- and that distinction is
    the whole point of this function.
    """
    best = None
    for run in runs:
        if (run.get("source"), run.get("hazard_type")) != (source, hazard):
            continue
        if run.get("status") not in ANSWERED:
            continue
        hours = age_hours(run.get("started_at", ""))
        if hours is not None and (best is None or hours < best):
            best = hours
    return best


def classify_stale(checks: dict, runs: list[dict]) -> tuple[list[str], list[str]]:
    """Split stale feeds into ours to fix, and theirs to wait out.

    Staleness alone cannot tell the two apart, and treating them the same
    makes the alert useless for months at a time: outside the monsoon the
    flood report simply stops, and a watcher that emails four times a day
    about that teaches its reader to delete the emails -- including the one
    that matters.
    """
    ours, theirs = [], []
    for name, check in checks.items():
        if not check.get("stale"):
            continue
        feed = FEED_FOR_CHECK.get(name)
        if feed is None:
            ours.append(f"{name}: stale, and no feed is mapped to it")
            continue

        since = asked_recently(runs, *feed)
        age_days = check.get("age_days")
        latest = check.get("latest_report") or check.get("latest_day") or "never"

        if since is None or since > ASKED_WITHIN_HOURS:
            when = "never" if since is None else f"{since:.0f}h ago"
            ours.append(
                f"{name}: newest is {latest} and the last answer from the source was {when}"
            )
        elif age_days is not None and age_days > QUIET_TOLERATED_DAYS:
            ours.append(
                f"{name}: the source has published nothing for {age_days} days -- long "
                "enough that a moved URL would look the same. Worth checking by hand"
            )
        else:
            theirs.append(
                f"{name}: newest is {latest}; ingestion ran {since:.0f}h ago and the "
                "source published nothing. The feed is quiet, not broken"
            )
    return ours, theirs


def run_problems(body: dict) -> list[str]:
    """Ingestion runs that a person should be told about.

    Only unresolved ones. `no_data` is never a problem to begin with: a day
    with no landslide anywhere is a correct, successful answer, and alerting
    on it would train the reader to ignore the alert.
    """
    problems = []
    runs = body.get("recent_runs", [])
    for run in runs:
        label = f"{run.get('source')} {run.get('hazard_type') or ''}".strip()
        hours = age_hours(run.get("started_at", ""))
        status = run.get("status")

        if status not in ("running", "failed") or superseded(run, runs):
            continue

        if status == "running" and hours is not None and STUCK_AFTER_HOURS < hours <= FAILURE_WINDOW_HOURS:
            problems.append(f"{label}: started {hours:.1f}h ago and never finished")
        elif status == "failed" and (hours is None or hours <= FAILURE_WINDOW_HOURS):
            when = f"{hours:.1f}h ago" if hours is not None else "recently"
            problems.append(f"{label}: run failed {when}")
    return problems


def describe(name: str, check: dict) -> str:
    """One line per check, with the detail that makes it actionable."""
    detail = {k: v for k, v in check.items() if k != "ok"}
    mark = "ok  " if check.get("ok") else "FAIL"
    return f"  {mark}  {name:20} {json.dumps(detail) if detail else ''}".rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=os.environ.get("SETUNER_API_BASE", DEFAULT_BASE),
        help="API origin to check (default: the deployed API)",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print(f"Checking {base}{READY_PATH}")
    try:
        body = fetch(base + READY_PATH)
    except Unreachable as exc:
        headline = f"UNREACHABLE: no readiness answer from {base} ({exc})"
        print(headline)
        summarise(headline, [])
        return 2

    checks = body.get("checks", {})
    lines = [describe(name, check) for name, check in checks.items()]

    failed = [name for name, check in checks.items() if not check.get("ok")]

    # The run log answers two questions readiness cannot: did the job run and
    # finish, and -- when a feed is stale -- was that us or the source?
    try:
        log = fetch(base + RUNS_PATH)
    except Unreachable as exc:
        log = {}
        lines.append(f"  FAIL  could not read the run log ({exc})")
    runs = run_problems(log)
    stale_ours, stale_theirs = classify_stale(checks, log.get("recent_runs", []))

    for problem in runs + stale_ours:
        lines.append(f"  FAIL  {problem}")
    for quiet in stale_theirs:
        lines.append(f"  note  {quiet}")
    print("\n".join(lines))

    trouble = []
    if failed:
        trouble.append("not ready: " + ", ".join(failed))
    if stale_ours:
        trouble.append("stale: " + "; ".join(stale_ours))
    if runs:
        trouble.append("runs: " + "; ".join(runs))

    if not trouble:
        headline = f"HEALTHY: {len(checks)} checks passing, ingestion running"
        if stale_theirs:
            n = len(stale_theirs)
            headline += (
                f" -- but {n} feed{'' if n == 1 else 's'} "
                f"{'has' if n == 1 else 'have'} gone quiet at the source"
            )
        print(headline)
        summarise(headline, lines)
        return 0

    headline = "PROBLEM -- " + " | ".join(trouble)
    print(headline)
    summarise(headline, lines)
    return 1


def summarise(headline: str, lines: list[str]) -> None:
    """Put the verdict on the workflow run page, not just in the log."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"## {headline}\n\n")
        if lines:
            handle.write("```\n" + "\n".join(lines) + "\n```\n")


if __name__ == "__main__":
    sys.exit(main())
