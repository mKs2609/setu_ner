"""
The daily job: ingest what is missing (reports and rainfall), match damage to
roads, re-score.

    cd apps/api
    python -m app.jobs.daily

One entrypoint for every scheduler -- a hosting platform's cron, the Docker
Compose loop, the Windows task -- so they cannot drift into running different
steps. Each step runs in its own process, in order, and a failure in one does
not stop the next: a landslide-report outage should not prevent flood data
from being scored.

WAKING THE DATABASE FIRST
Neon suspends compute when idle, and the first connection of the day is
routinely refused while it wakes. Whichever step ran first used to absorb
that and fail -- on 12 and 13 November 2026 it was flood ingestion, twice,
and the watcher correctly reported that we had stopped asking the portal for
flood reports. So the job now wakes the database itself before any step runs,
the same way it probes the portal.

WHERE IT CAN RUN
The ASDMA portal answers from India in under a second and does not answer
GitHub's US runners at all -- found on the first hosted run, which sat 17
minutes on its first request and ingested nothing. So before fetching, the
job checks the portal answers within PORTAL_PROBE_TIMEOUT_S. If it does not,
ingestion is skipped with that reason instead of retrying for an hour, and
matching and scoring still run on what is already stored (the scorer then
refuses stale data, which is the alert). Run the job from a machine in India
-- see scripts/scheduling/README.md.

EXIT CODE
0 when every step succeeded. Non-zero when any failed, including the scorer
refusing a stale report -- which is exactly the situation a platform's
failed-job alert should surface.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone

STEPS = [
    ("flood ingestion", ["-m", "app.services.ingestion.run", "--hazard", "flood", "--catch-up"]),
    ("landslide ingestion", ["-m", "app.services.ingestion.run", "--hazard", "landslide", "--catch-up"]),
    # NASA, not ASDMA: runs even when the portal is down. Before scoring,
    # because a model trained with rainfall needs it; if it fails, scoring
    # still runs and serves persistence for the rows it cannot score
    # (district_model.for_inputs), which the stored forecasts record.
    ("rainfall ingestion", ["-m", "app.services.weather.ingest", "--catch-up"]),
    ("damage matching", ["-m", "app.services.model.damage_matching"]),
    ("scoring", ["-m", "app.services.model.score"]),
]

STEP_TIMEOUT_S = 45 * 60
PORTAL_PROBE_TIMEOUT_S = 20
INGESTION_STEPS = {"flood ingestion", "landslide ingestion"}

# How long to keep knocking before deciding the database is genuinely down.
# A suspended Neon instance answers within a few seconds; these delays cover
# roughly forty, which is far more than one has ever needed and still short
# enough that a real outage is reported promptly rather than hung on.
DB_WAKE_DELAYS_S = (2, 5, 10, 20)


def portal_reachable(timeout: float = PORTAL_PROBE_TIMEOUT_S) -> tuple[bool, str]:
    """One quick request to the DRIMS portal, no retries."""
    from app.services.ingestion.http_client import PoliteClient
    from app.services.ingestion.sources import drims

    try:
        PoliteClient(timeout=timeout, max_retries=0).fetch(f"{drims.BASE}/download?type=flood")
        return True, "portal answered"
    except Exception as exc:  # noqa: BLE001 -- the reason is reported
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


def database_awake(delays: tuple[int, ...] = DB_WAKE_DELAYS_S) -> tuple[bool, str]:
    """Knock until the database answers, or give up and say why.

    Every step opens its own connection in its own process, so this does not
    hand anything to them -- it wakes the *server*, so that the first step of
    the day is no longer the one that pays for the cold start.
    """
    from sqlalchemy import text

    from app.db.session import SessionLocal

    last = ""
    # One attempt per delay, then a final attempt with nothing to wait for
    # after it -- which is what the trailing None marks.
    for attempt, delay in enumerate([*delays, None], start=1):
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            if attempt == 1:
                return True, "answered immediately"
            return True, f"answered on attempt {attempt}"
        except Exception as exc:  # noqa: BLE001 -- the reason is reported
            last = f"{type(exc).__name__}: {str(exc)[:160]}"
            if delay is None:
                break
            print(f"    database not awake yet ({last}); waiting {delay}s", flush=True)
            time.sleep(delay)
    return False, last


def main() -> int:
    started = time.monotonic()
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] daily job starting", flush=True)
    failures = []

    # Before anything else: every step below needs the database, and the one
    # that runs first should not be the one that absorbs its cold start.
    awake, db_why = database_awake()
    if awake:
        print(f"--- database: {db_why}", flush=True)
    else:
        print(
            f"--- database did not answer after {len(DB_WAKE_DELAYS_S)} retries "
            f"({db_why}). Every step needs it, so none are run.",
            flush=True,
        )
        print(
            f"daily job finished WITH FAILURES in {time.monotonic() - started:.0f}s: database",
            flush=True,
        )
        return 1

    reachable, why = portal_reachable()
    if not reachable:
        print(
            f"--- ASDMA portal did not answer within {PORTAL_PROBE_TIMEOUT_S}s ({why}). "
            "It does not answer from outside India; run this job from a machine in "
            "India (scripts/scheduling/README.md). Skipping ingestion.",
            flush=True,
        )
        failures.append("portal unreachable")

    for name, args in STEPS:
        if name in INGESTION_STEPS and not reachable:
            continue
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, *args], timeout=STEP_TIMEOUT_S, capture_output=True, text=True
            )
            code = result.returncode
            output = (result.stdout + result.stderr).strip()
        except subprocess.TimeoutExpired:
            code, output = 124, f"timed out after {STEP_TIMEOUT_S}s"
        status = "ok" if code == 0 else f"FAILED (exit {code})"
        print(f"--- {name}: {status} in {time.monotonic() - t0:.0f}s", flush=True)
        for line in output.splitlines()[-20:]:
            print(f"    {line}", flush=True)
        if code != 0:
            failures.append(name)

    total = time.monotonic() - started
    if failures:
        print(f"daily job finished WITH FAILURES in {total:.0f}s: {', '.join(failures)}", flush=True)
        return 1
    print(f"daily job finished in {total:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
