"""
A deliberately cautious HTTP client for pulling from government portals.

WHY THIS EXISTS RATHER THAN BARE `requests`
Everything this project ingests comes from public-sector sites run on modest
infrastructure, and we are an uninvited guest on them. A scraper that
retries hard on failure, runs unthrottled, or downloads whatever it is
handed is the kind of thing that gets a project blocked -- deservedly. The
rules below are the difference between "polite automated reader" and
"denial of service with good intentions".

WHAT IT ENFORCES

  robots.txt          Fetched once per host and cached. A disallowed path
                      raises rather than being fetched. A 404 robots.txt
                      means no rules published, which by convention is
                      allow-all -- that is the case for cwc.gov.in and
                      asdma.assam.gov.in; sdrf.assam.gov.in publishes an
                      explicit empty Disallow, which also means allow-all.

  crawl delay         A minimum gap between requests to the same host,
                      enforced process-wide. robots.txt Crawl-delay wins if
                      it asks for longer than our default.

  retries             Only on genuinely transient failures: timeouts,
                      connection errors, and 5xx / 429. A 4xx is a real
                      answer -- retrying it just hammers the server for
                      something it already told us it will not give.

  backoff             Exponential with jitter. Jitter matters because a
                      scheduled job retrying on a fixed schedule turns into
                      a synchronised thundering herd across restarts.

  timeouts            On every request, always. A hung socket with no
                      timeout is how a scheduled job silently stops.

  size cap            Responses are streamed and abandoned past a limit, so
                      a redirect to something enormous cannot exhaust memory.

  honest UA           Identifies the project and that it is non-commercial,
                      so an administrator who sees it in their logs can tell
                      what it is.

WHAT IT DOES NOT DO
No concurrency against a single host, and no cleverness about evading rate
limits or blocks. If a source blocks us, the correct response is to stop and
talk to them, not to work around it.
"""

from __future__ import annotations

import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = (
    "SetuNER-hazard-ingestion/0.1 "
    "(+https://github.com/mKs2609/setu_ner; non-commercial research; respects robots.txt)"
)

DEFAULT_TIMEOUT = 45.0
DEFAULT_CRAWL_DELAY = 3.0
DEFAULT_MAX_BYTES = 40 * 1024 * 1024  # 40 MB; the daily report PDF is under 1 MB
DEFAULT_MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """A fetch that failed in a way the caller should record, not crash on."""


class RobotsDisallowed(FetchError):
    """The host's robots.txt forbids this path. Never retried, never bypassed."""


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    content_type: str | None

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def is_pdf(self) -> bool:
        return self.content[:5] == b"%PDF-"


class PoliteClient:
    """One instance per ingestion run. Safe to share across sources: the
    crawl-delay bookkeeping is per host and guarded by a lock."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        crawl_delay: float = DEFAULT_CRAWL_DELAY,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_retries: int = DEFAULT_MAX_RETRIES,
        obey_robots: bool = True,
        opener: urllib.request.OpenerDirector | None = None,
        sleep=time.sleep,
    ) -> None:
        self.timeout = timeout
        self.crawl_delay = crawl_delay
        self.max_bytes = max_bytes
        self.max_retries = max_retries
        self.obey_robots = obey_robots
        # Cookie support matters: the daily-report download is a Laravel form
        # that hands out a CSRF token tied to a session cookie.
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor()
        )
        self._sleep = sleep
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # -- politeness -------------------------------------------------------

    def _wait_turn(self, host: str, required: float) -> None:
        with self._lock:
            last = self._last_request_at.get(host)
            now = time.monotonic()
            if last is not None:
                gap = now - last
                if gap < required:
                    self._sleep(required - gap)
            self._last_request_at[host] = time.monotonic()

    def _robots_for(self, scheme: str, host: str) -> RobotFileParser | None:
        if host in self._robots:
            return self._robots[host]
        parser: RobotFileParser | None = None
        try:
            req = urllib.request.Request(
                f"{scheme}://{host}/robots.txt", headers={"User-Agent": USER_AGENT}
            )
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read(self.max_bytes).decode("utf-8", errors="replace")
            parser = RobotFileParser()
            parser.parse(body.splitlines())
        except urllib.error.HTTPError as exc:
            # No robots.txt published (typically 404) means no restrictions.
            if exc.code not in (401, 403):
                parser = None
            else:
                # 401/403 on robots.txt conventionally means "stay out".
                parser = RobotFileParser()
                parser.parse(["User-agent: *", "Disallow: /"])
        except Exception:
            # Could not determine the rules. Proceed, but at the default delay;
            # failing closed here would make ingestion depend on robots.txt
            # uptime, which is its own fragility.
            parser = None
        self._robots[host] = parser
        return parser

    def _check_allowed(self, url: str) -> float:
        parsed = urlparse(url)
        host, scheme = parsed.netloc, parsed.scheme or "https"
        delay = self.crawl_delay
        if not self.obey_robots:
            return delay
        rules = self._robots_for(scheme, host)
        if rules is not None:
            if not rules.can_fetch(USER_AGENT, url):
                raise RobotsDisallowed(f"robots.txt disallows fetching {url}")
            declared = rules.crawl_delay(USER_AGENT)
            if declared:
                delay = max(delay, float(declared))
        return delay

    # -- fetching ---------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """GET, or POST when `data` is given. Retries only transient failures."""
        delay = self._check_allowed(url)
        host = urlparse(url).netloc

        request_headers = {"User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait_turn(host, delay)
            req = urllib.request.Request(url, data=data, headers=request_headers)
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    content = resp.read(self.max_bytes + 1)
                    if len(content) > self.max_bytes:
                        raise FetchError(
                            f"Response from {url} exceeded {self.max_bytes} bytes; "
                            f"refusing to buffer it."
                        )
                    return Response(
                        url=resp.geturl(),
                        status=resp.status,
                        content=content,
                        content_type=resp.headers.get("Content-Type"),
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in RETRY_STATUSES:
                    # A real answer from the server. Do not hammer it.
                    raise FetchError(f"{url} returned HTTP {exc.code}") from exc
            except FetchError:
                raise
            except Exception as exc:
                last_error = exc

            if attempt < self.max_retries:
                backoff = (2**attempt) * delay
                self._sleep(backoff + random.uniform(0, delay))

        raise FetchError(
            f"{url} failed after {self.max_retries + 1} attempts: {last_error}"
        ) from last_error
