"""
The judgement calls in check_deployment.py, against fake servers.

    python scripts/monitoring/test_check_deployment.py

Standard library only, and run by CI. It lives beside the script rather than
in apps/api/tests because it tests a monitoring script, not the API, and
reaching across the repo to import it would be worse than a second entrypoint.

WHAT IS WORTH TESTING HERE
Three decisions, each of which is wrong in both directions:

  retrying    An answer saying "not ready" must be believed at once, while no
              answer at all must be retried -- the API sleeps, and a cold
              start looks exactly like an outage for about a minute. Backwards
              and you either delay every real alert or page on every wake-up.

  staleness   Readiness reports `stale` without failing on it, on purpose
              (render.yaml gates traffic on that endpoint). The watcher has to
              fail on it anyway, or the quiet failure it exists for is invisible.

  runs        A hung run must be reported, a recent failure must be reported,
              and `no_data` must NOT be -- a day with no landslide anywhere is
              a correct answer, and alerting on it teaches the reader to
              ignore alerts.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_deployment as cd  # noqa: E402

cd.BACKOFF_S = 0
cd.TIMEOUT_S = 5

HEALTHY = {"ready": True, "checks": {"database": {"ok": True}}}
NO_RUN_PROBLEMS: dict = {"recent_runs": []}


def hours_ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def serve(ready_status: int, ready_body: dict | None, runs_body: dict | None = None):
    """A server answering both paths the script asks for, counting requests."""
    seen = [0]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith(cd.RUNS_PATH):
                status, body = 200, (runs_body if runs_body is not None else NO_RUN_PROBLEMS)
            else:
                seen[0] += 1
                status, body = ready_status, ready_body
            payload = json.dumps(body).encode() if body is not None else b"<html>oops</html>"
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def run(server) -> int:
    sys.argv = ["check_deployment", "--base", f"http://127.0.0.1:{server.server_address[1]}"]
    return cd.main()


def case(name: str, expect: int, *args, requests: int | None = None):
    print(f"\n=== {name} ===")
    server, seen = serve(*args)
    try:
        code = run(server)
    finally:
        server.shutdown()
    assert code == expect, f"{name}: expected exit {expect}, got {code}"
    if requests is not None:
        assert seen[0] == requests, f"{name}: expected {requests} requests, got {seen[0]}"


def main() -> int:
    # --- retrying -----------------------------------------------------------
    # A 503 carrying a readiness body is a verdict, not a hiccup.
    case("503 with a body is believed immediately", 1, 503,
         {"ready": False, "checks": {"database": {"ok": False}}}, requests=1)

    # A gateway error with no body is the platform, not the app: cold start.
    case("502 with no body is retried, then reported", 2, 502, None,
         requests=cd.ATTEMPTS)

    print("\n=== nothing listening ===")
    sys.argv = ["check_deployment", "--base", "http://127.0.0.1:59999"]
    assert cd.main() == 2

    # --- staleness ----------------------------------------------------------
    # The whole point: ready is true, every check is ok, and the data is old.
    # Readiness passes this on purpose; the watcher must not.
    case("ready but a feed is stale", 1, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-18", "age_days": 8, "stale": True},
        },
    })

    # --- runs ---------------------------------------------------------------
    case("a run that started and never finished", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "running", "started_at": hours_ago(cd.STUCK_AFTER_HOURS + 1)},
        ],
    })

    case("a run still going, inside the window", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "running", "started_at": hours_ago(cd.STUCK_AFTER_HOURS - 1)},
        ],
    })

    case("a run stuck for days stops alerting once the day is recovered", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "running", "started_at": hours_ago(cd.FAILURE_WINDOW_HOURS + 12)},
        ],
    })

    # The incident is over once the feed has run again: the scheduler re-owes
    # the day and inserts a new run, so a later success means recovered.
    case("a stuck run a later success has already recovered", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "running", "started_at": hours_ago(cd.STUCK_AFTER_HOURS + 1)},
        ],
    })

    # ...but a success on a *different* feed recovers nothing.
    case("another feed succeeding does not clear it", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "running", "started_at": hours_ago(cd.STUCK_AFTER_HOURS + 1)},
        ],
    })

    # Nor does a success from *before* the failure.
    case("an earlier success does not clear a later failure", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "failed", "started_at": hours_ago(2)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "success", "started_at": hours_ago(26)},
        ],
    })

    case("a recent failure", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "status": "failed", "started_at": hours_ago(2)},
        ],
    })

    case("an old failure is history, not an alert", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "status": "failed", "started_at": hours_ago(cd.FAILURE_WINDOW_HOURS + 24)},
        ],
    })

    case("no_data is a correct answer, not a problem", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "landslide",
             "status": "no_data", "started_at": hours_ago(1)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "success", "started_at": hours_ago(1)},
        ],
    })

    # --- a stale feed: ours to fix, or theirs to wait out? ------------------
    # Outside the monsoon the flood report stops for months. Ingestion keeps
    # reaching the portal and keeps being told there is nothing, which is a
    # working pipeline and must not page anyone.
    case("a feed the source has gone quiet on is not a fault", 0, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-29",
                               "age_days": 5, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "no_data", "started_at": hours_ago(2)},
        ],
    })

    # The same staleness with nobody asking is our problem, and must fail.
    case("the same staleness with no recent fetch does fail", 1, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-29",
                               "age_days": 5, "stale": True},
        },
    }, {"recent_runs": []})

    # A fetch so old it no longer counts as "we are still asking".
    case("a fetch older than the window does not excuse staleness", 1, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-29",
                               "age_days": 5, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "no_data", "started_at": hours_ago(cd.ASKED_WITHIN_HOURS + 6)},
        ],
    })

    # Quiet for long enough that a moved URL would look identical. A person
    # should look, so the alert comes back.
    case("a very long silence is reported anyway", 1, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-08-01",
                               "age_days": cd.QUIET_TOLERATED_DAYS + 1, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "no_data", "started_at": hours_ago(2)},
        ],
    })

    # A quiet flood feed must not excuse a stale rainfall feed.
    case("one feed being quiet does not cover another", 1, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-29",
                               "age_days": 5, "stale": True},
            "rainfall_freshness": {"ok": True, "latest_day": "2026-09-10",
                                   "age_days": 20, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "status": "no_data", "started_at": hours_ago(2)},
        ],
    })

    # --- the happy path -----------------------------------------------------
    case("healthy", 0, 200, HEALTHY)

    print("\nall nineteen cases behave correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
