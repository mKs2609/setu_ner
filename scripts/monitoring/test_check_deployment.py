"""
The failure paths of check_deployment.py, against fake servers.

    python scripts/monitoring/test_check_deployment.py

Standard library only, and run by CI. It lives beside the script rather than
in apps/api/tests because it tests a monitoring script, not the API, and
reaching across the repo to import it would be worse than a second entrypoint.

WHAT IS WORTH TESTING HERE
One distinction, and it is the whole design: an answer that says "not ready"
must be believed immediately, while no answer at all must be retried, because
the API sleeps and a cold start looks exactly like an outage for about a
minute. Getting that backwards either delays every real alert by minutes or
pages the owner every time the instance wakes up.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_deployment as cd  # noqa: E402

cd.BACKOFF_S = 0
cd.TIMEOUT_S = 5

NOT_READY = {
    "ready": False,
    "checks": {
        "database": {"ok": True},
        "data_freshness": {
            "ok": False,
            "latest_report": "2026-09-18",
            "age_days": 8,
            "stale": True,
        },
    },
}


def serve(status: int, body: dict | None):
    """A one-response server on a free port, plus a counter of requests seen."""
    seen = [0]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen[0] += 1
            payload = (
                json.dumps(body).encode() if body is not None else b"<html>bad gateway</html>"
            )
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


def run(base: str) -> int:
    sys.argv = ["check_deployment", "--base", base]
    return cd.main()


def main() -> int:
    # A 503 carrying a readiness body is a verdict, not a hiccup: believed at
    # once, so the alert is not delayed by a minute of pointless retries.
    server, seen = serve(503, NOT_READY)
    code = run(f"http://127.0.0.1:{server.server_address[1]}")
    assert code == 1, f"expected NOT READY (1), got {code}"
    assert seen[0] == 1, f"a real verdict must not be retried; {seen[0]} requests made"
    server.shutdown()

    # A gateway error with no readiness body is the platform, not the app --
    # which is what a cold start looks like. Retried, then reported.
    server, seen = serve(502, None)
    code = run(f"http://127.0.0.1:{server.server_address[1]}")
    assert code == 2, f"expected UNREACHABLE (2), got {code}"
    assert seen[0] == cd.ATTEMPTS, f"expected {cd.ATTEMPTS} attempts, got {seen[0]}"
    server.shutdown()

    # Nothing listening at all.
    assert run("http://127.0.0.1:59999") == 2

    # Ready can be false on a 200 as well; the body decides, not the status.
    server, _ = serve(200, {"ready": False, "checks": {"database": {"ok": False}}})
    code = run(f"http://127.0.0.1:{server.server_address[1]}")
    assert code == 1, f"expected NOT READY (1), got {code}"
    server.shutdown()

    # And the happy path.
    server, _ = serve(200, {"ready": True, "checks": {"database": {"ok": True}}})
    code = run(f"http://127.0.0.1:{server.server_address[1]}")
    assert code == 0, f"expected READY (0), got {code}"
    server.shutdown()

    print("\nall five paths behave correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
