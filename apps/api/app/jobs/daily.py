"""
The daily job: ingest what is missing, match damage to roads, re-score.

    cd apps/api
    python -m app.jobs.daily

One entrypoint for every scheduler -- a hosting platform's cron, the Docker
Compose loop, the Windows task -- so they cannot drift into running different
steps. Each step runs in its own process, in order, and a failure in one does
not stop the next: a landslide-report outage should not prevent flood data
from being scored.

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
    ("damage matching", ["-m", "app.services.model.damage_matching"]),
    ("scoring", ["-m", "app.services.model.score"]),
]

STEP_TIMEOUT_S = 45 * 60


def main() -> int:
    started = time.monotonic()
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] daily job starting", flush=True)
    failures = []
    for name, args in STEPS:
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
