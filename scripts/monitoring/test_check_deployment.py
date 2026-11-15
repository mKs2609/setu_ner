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
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_deployment as cd  # noqa: E402

# The acknowledgements an operator has actually committed. Captured before the
# suite neutralises them: the exit-code cases below test the rules, not
# whichever feeds happen to be acknowledged today, and a real entry for
# data_freshness would otherwise silence the 14-day-cap case.
SHIPPED_ACKNOWLEDGEMENTS = cd.ACKNOWLEDGED_FILE

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
    cd.ACKNOWLEDGED_FILE = Path("tests-use-no-acknowledgements.json")

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
             "target_date": "2026-10-01",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-01",
             "status": "running", "started_at": hours_ago(cd.STUCK_AFTER_HOURS + 1)},
        ],
    })

    # ...but a success on a *different* feed recovers nothing.
    case("another feed succeeding does not clear it", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-01",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-01",
             "status": "running", "started_at": hours_ago(cd.STUCK_AFTER_HOURS + 1)},
        ],
    })

    # Nor does a success from *before* the failure.
    case("an earlier success does not clear a later failure", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-01",
             "status": "failed", "started_at": hours_ago(2)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-01",
             "status": "success", "started_at": hours_ago(26)},
        ],
    })

    # 3 Oct 2026, from production: one catch-up run works newest day first,
    # so a success for an older day landed four seconds after a failure for a
    # newer one and hid it. A day is only recovered by a run for that day.
    case("a later success for a different day does not clear a failure", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-09-30",
             "status": "success", "started_at": hours_ago(2)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-01",
             "status": "failed", "started_at": hours_ago(2.01)},
        ],
    })

    # ...and once that same day is refetched, it goes quiet.
    case("the same day being refetched does clear it", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-01",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-01",
             "status": "failed", "started_at": hours_ago(2)},
        ],
    })

    # A run with no target day cannot be matched, so it is never excused.
    case("a failure with no target day is always reported", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "status": "failed", "started_at": hours_ago(2)},
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

    # --- a source that is erroring, not merely quiet -----------------------
    # 12 Oct 2026, from production: NASA's OPeNDAP service returned HTTP 500 on
    # everything for two days. Catch-up still asked for the newest day, got the
    # normal "not published yet", and the quiet-source rule read that single
    # answer as proof the source was healthy -- while two older days were
    # failing. The run failures still failed the check, but the note said the
    # feed was "quiet, not broken" about a feed that was returning 500s.
    case("a feed that is erroring is not reported as quiet", 1, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "rainfall_freshness": {"ok": True, "latest_day": "2026-10-08",
                                   "age_days": 4, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-11",
             "status": "no_data", "started_at": hours_ago(16)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-10",
             "status": "failed", "started_at": hours_ago(16)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-09",
             "status": "failed", "started_at": hours_ago(16)},
        ],
    })

    # The genuinely quiet case must keep working: answers, no failures.
    case("a quiet feed with no failures is still excused", 0, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-29",
                               "age_days": 5, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-04",
             "status": "no_data", "started_at": hours_ago(2)},
        ],
    })

    # An old failure, long since recovered, must not re-label a quiet feed.
    case("a failure older than the window does not un-quiet a feed", 0, 200, {
        "ready": True,
        "checks": {
            "database": {"ok": True},
            "data_freshness": {"ok": True, "latest_report": "2026-09-29",
                               "age_days": 5, "stale": True},
        },
    }, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-04",
             "status": "no_data", "started_at": hours_ago(2)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-09-01",
             "status": "failed", "started_at": hours_ago(cd.ASKED_WITHIN_HOURS + 12)},
        ],
    })

    # --- a source that answered with the wrong document ---------------------
    # 16 Oct 2026: ASDMA served the report printed 2025-05-16 when asked for
    # 2026-10-16. Refusing it is correct, and a person has to know -- but it
    # is not the same event as "we could not reach them".
    case("a rejected day is reported", 1, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-16",
             "status": "rejected", "started_at": hours_ago(16)},
        ],
    })

    # Catch-up stops creating these after two days, so the last one ages out
    # of the window and the alerting goes quiet without anyone silencing it.
    case("an old rejection has gone quiet by itself", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-16",
             "status": "rejected", "started_at": hours_ago(cd.FAILURE_WINDOW_HOURS + 6)},
        ],
    })

    # A refetch of that same day clears it, exactly as for a failure.
    case("a success for the same day clears a rejection", 0, 200, HEALTHY, {
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-16",
             "status": "success", "started_at": hours_ago(1)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-16",
             "status": "rejected", "started_at": hours_ago(16)},
        ],
    })

    # --- the happy path -----------------------------------------------------
    case("healthy", 0, 200, HEALTHY)

    # --- what the report actually says --------------------------------------
    # These read the strings. The 12 October bug changed no exit code: the
    # failed runs failed the check correctly, and only the explanation printed
    # next to them was wrong. Exit-code cases cannot catch that.
    print("\n=== wording: a stale feed that is erroring ===")
    ours, theirs = cd.classify_stale(
        {"rainfall_freshness": {"ok": True, "latest_day": "2026-10-08",
                                "age_days": 4, "stale": True}},
        [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-11", "status": "no_data",
             "started_at": hours_ago(16)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-09", "status": "failed",
             "started_at": hours_ago(16)},
        ],
    )
    note = " ".join(theirs)
    assert "quiet, not broken" not in note, f"still calls an erroring feed quiet: {note}"
    assert "returning errors" in note, f"does not say the source is erroring: {note}"
    print(" ", note)

    print("\n=== wording: a genuinely quiet feed ===")
    ours, theirs = cd.classify_stale(
        {"data_freshness": {"ok": True, "latest_report": "2026-09-29",
                            "age_days": 5, "stale": True}},
        [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-04", "status": "no_data",
             "started_at": hours_ago(2)},
        ],
    )
    assert not ours, ours
    assert "quiet, not broken" in " ".join(theirs), theirs
    print(" ", " ".join(theirs))

    print("\n=== wording: two owed days are two distinct lines ===")
    problems = cd.run_problems({
        "recent_runs": [
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-10", "status": "failed",
             "started_at": hours_ago(16)},
            {"source": "nasa_gpm_imerg_late", "hazard_type": "rainfall",
             "target_date": "2026-10-09", "status": "failed",
             "started_at": hours_ago(16)},
        ],
    })
    assert len(problems) == 2, problems
    assert len(set(problems)) == 2, f"two owed days printed identically: {problems}"
    assert "2026-10-09" in " ".join(problems) and "2026-10-10" in " ".join(problems), problems
    for line in problems:
        print(" ", line)

    print("\n=== wording: a rejection says what to do about it ===")
    problems = cd.run_problems({
        "recent_runs": [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-16",
             "status": "rejected", "started_at": hours_ago(16)},
        ],
    })
    assert len(problems) == 1, problems
    line = problems[0]
    assert "2026-10-16" in line, line
    assert "wrong day" in line, line
    assert "Needs a person" in line, line
    assert "run failed" not in line, f"a rejection must not read as a failure: {line}"
    print(" ", line)

    print("\n=== wording: a feed serving wrong documents is not quiet ===")
    ours, theirs = cd.classify_stale(
        {"data_freshness": {"ok": True, "latest_report": "2026-10-15",
                            "age_days": 5, "stale": True}},
        [
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-20", "status": "no_data",
             "started_at": hours_ago(16)},
            {"source": "drims_assam_daily_report", "hazard_type": "flood",
             "target_date": "2026-10-16", "status": "rejected",
             "started_at": hours_ago(16)},
        ],
    )
    note = " ".join(theirs)
    assert "quiet, not broken" not in note, f"still calls it quiet: {note}"
    print(" ", note)

    # --- an operator who looked, and said so --------------------------------
    # 15 Nov 2026: the 14-day cap fired on the flood feed, as designed, and
    # the by-hand check found the benign answer -- ASDMA stopped for the
    # season, the URL had not moved. There was nowhere to put that answer, so
    # the rule would have asked again four times a day until the monsoon.
    # --- an operator who looked, and said so --------------------------------
    # 15 Nov 2026: the 14-day cap fired on the flood feed, as designed, and
    # the by-hand check found the benign answer -- ASDMA stopped for the
    # season, the URL had not moved. There was nowhere to put that answer, so
    # the rule would have asked again four times a day until the monsoon.
    print("\n=== acknowledgement: a checked silence is a note, not a failure ===")
    import json as _json
    import os as _os
    import tempfile as _tempfile

    def _temp_file(text):
        """A throwaway file holding `text`. mkstemp's descriptor is closed
        first: Windows will not unlink a file that is still open."""
        fd, name = _tempfile.mkstemp(suffix=".json")
        _os.close(fd)
        path = Path(name)
        path.write_text(text, encoding="utf-8")
        return path

    def _with_ack(entries, today):
        """Ask acknowledged_quiet about a temporary acknowledgements file."""
        original = cd.ACKNOWLEDGED_FILE
        cd.ACKNOWLEDGED_FILE = _temp_file(_json.dumps(entries))
        try:
            return cd.acknowledged_quiet("data_freshness", today=today)
        finally:
            cd.ACKNOWLEDGED_FILE.unlink(missing_ok=True)
            cd.ACKNOWLEDGED_FILE = original

    ok, live = _with_ack(
        {"data_freshness": {"quiet_until": "2026-12-20", "checked_on": "2026-11-15",
                            "note": "off-season"}},
        date(2026, 11, 20),
    )
    assert ok and "2026-11-15" in live and "off-season" in live, live
    print(" ", live)

    # A note is free text. An earlier version decided whether a feed was
    # acknowledged by looking for "not acknowledged" inside the message, so an
    # operator writing that phrase would have silently un-acknowledged it.
    awkward, _ = _with_ack(
        {"data_freshness": {"quiet_until": "2026-12-20", "checked_on": "2026-11-15",
                            "note": "previously not acknowledged; now checked"}},
        date(2026, 11, 20),
    )
    assert awkward is True, "the note's wording must not change the verdict"

    # It expires. Silence is never permanent, and the backstop returns on its
    # own rather than needing someone to remember to remove it.
    expired, _ = _with_ack(
        {"data_freshness": {"quiet_until": "2026-12-20", "checked_on": "2026-11-15"}},
        date(2026, 12, 21),
    )
    assert expired is False, "an expired acknowledgement must not silence"
    print("  expired -> not acknowledged, as it should be")

    # On its last day it still counts.
    assert _with_ack(
        {"data_freshness": {"quiet_until": "2026-12-20", "checked_on": "2026-11-15"}},
        date(2026, 12, 20),
    )[0] is True, "quiet_until should be inclusive"

    # Another feed's acknowledgement says nothing about this one.
    assert _with_ack(
        {"rainfall_freshness": {"quiet_until": "2027-01-01", "checked_on": "2026-11-15"}},
        date(2026, 11, 20),
    )[0] is False, "an acknowledgement must not cover a feed it does not name"

    # A file that cannot be parsed must not silence anything.
    original = cd.ACKNOWLEDGED_FILE
    broken = _temp_file("{not json")
    cd.ACKNOWLEDGED_FILE = broken
    try:
        ok, said = cd.acknowledged_quiet("data_freshness", today=date(2026, 11, 20))
    finally:
        cd.ACKNOWLEDGED_FILE = original
        broken.unlink(missing_ok=True)
    assert ok is False and "could not read" in said, said
    print("  malformed file ->", said[:60])

    # No file at all is simply no acknowledgement.
    cd.ACKNOWLEDGED_FILE = Path("does-not-exist-anywhere.json")
    try:
        assert cd.acknowledged_quiet("data_freshness", today=date(2026, 11, 20))[0] is False
    finally:
        cd.ACKNOWLEDGED_FILE = original
    print("  missing file -> not acknowledged")

    # And the committed file must be valid, or it silences nothing in production.
    shipped = _json.loads(SHIPPED_ACKNOWLEDGEMENTS.read_text(encoding="utf-8"))
    for key, entry in shipped.items():
        if key.startswith("_"):
            continue
        assert "quiet_until" in entry and "checked_on" in entry, key
        date.fromisoformat(entry["quiet_until"])
        date.fromisoformat(entry["checked_on"])
    print(f"  shipped acknowledged.json parses, {len(shipped) - 1} live entry/entries")


    # The safety property of the whole feature: an acknowledgement excuses a
    # source that has gone quiet, and nothing else. A feed nobody is asking is
    # our fault whatever anyone has written down about it.
    print("\n=== acknowledgement: covers a quiet source, and nothing else ===")
    live_ack = _temp_file(_json.dumps(
        {"data_freshness": {"quiet_until": "2099-01-01",
                            "checked_on": "2026-11-15"}}
    ))
    cd.ACKNOWLEDGED_FILE = live_ack
    try:
        stale_check = {"data_freshness": {"ok": True, "latest_report": "2026-10-31",
                                          "age_days": 40, "stale": True}}
        # Nobody has asked the source in days: ours, acknowledgement or not.
        ours, theirs = cd.classify_stale(stale_check, [])
        assert ours and not theirs, f"an unasked feed must stay ours: {ours} {theirs}"
        print("  nobody asking   ->", ours[0][:72])

        # Asked recently and genuinely quiet: the acknowledgement applies.
        asked = [{"source": "drims_assam_daily_report", "hazard_type": "flood",
                  "status": "no_data", "started_at": hours_ago(2)}]
        ours, theirs = cd.classify_stale(stale_check, asked)
        assert theirs and not ours, f"an acknowledged quiet feed is a note: {ours}"
        print("  asked, quiet    ->", theirs[0][:72])

        # Asked recently but erroring: still reported, acknowledgement or not.
        erroring = asked + [{"source": "drims_assam_daily_report",
                             "hazard_type": "flood", "status": "failed",
                             "started_at": hours_ago(2)}]
        ours, theirs = cd.classify_stale(stale_check, erroring)
        assert not any("checked by hand" in t for t in theirs), (
            f"an erroring feed must not read as acknowledged: {theirs}"
        )
        print("  asked, erroring ->", (theirs or ours)[0][:72])
    finally:
        cd.ACKNOWLEDGED_FILE = Path("tests-use-no-acknowledgements.json")
        live_ack.unlink(missing_ok=True)


    print("\nall twenty-eight cases and six wording checks behave correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
