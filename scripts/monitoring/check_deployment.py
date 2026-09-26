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

DEFAULT_BASE = "https://setuner-api.onrender.com"
PATH = "/api/v1/health/ready"

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
    url = args.base.rstrip("/") + PATH

    print(f"Checking {url}")
    try:
        body = fetch(url)
    except Unreachable as exc:
        headline = f"UNREACHABLE: no readiness answer from {args.base} ({exc})"
        print(headline)
        summarise(headline, [])
        return 2

    checks = body.get("checks", {})
    lines = [describe(name, check) for name, check in checks.items()]
    print("\n".join(lines))

    failed = [name for name, check in checks.items() if not check.get("ok")]
    if body.get("ready") and not failed:
        headline = f"READY: all {len(checks)} checks passing"
        print(headline)
        summarise(headline, lines)
        return 0

    headline = f"NOT READY: {', '.join(failed) if failed else 'ready=false'}"
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
