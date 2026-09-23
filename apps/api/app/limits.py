"""
Limits on the endpoints anyone can call.

WHY THIS EXISTS
Planning and scenario simulation are public on purpose -- being able to try
the thing without credentials is most of why it is useful. But both do real
work: shortest-path trees over 110k edges, an LP, several hundred megabytes
of peak memory between them. On a 512 MB instance, a handful of concurrent
requests is the difference between "slow" and "the process is killed and
every other user's request dies with it".

Two separate protections, because they stop different things:

  concurrency   How many heavy requests run at once. Protects memory. A
                request that cannot get a slot is turned away immediately
                with 429 rather than queued -- queueing on a single core
                just moves the timeout somewhere less visible.

  per-IP rate   How many heavy requests one source may make over a window.
                Protects against one client holding the only slot in a loop
                while everyone else gets 429.

WHAT THIS IS NOT
Not a security boundary, and not a substitute for one. It is in-process, so
it counts per worker (the deployment runs a single worker, so today that is
the whole service), it resets on restart, and it trusts a proxy header for
the client address. It raises the cost of being a nuisance; it does not stop
a determined attacker, and nothing here protects data -- that is what the
operator tokens do.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request

from app.config import get_settings

# Heavy requests per address per window.
WINDOW_SECONDS = 300
MAX_HEAVY_PER_WINDOW = 30

# Addresses tracked at once. Past this, the oldest is dropped: an attacker
# rotating addresses must not grow this dictionary without bound.
MAX_TRACKED_CLIENTS = 10_000

_lock = threading.Lock()
_seen: OrderedDict[str, deque[float]] = OrderedDict()

# One semaphore for every heavy endpoint, not one each: the memory they
# compete for is the same memory.
_slots = threading.BoundedSemaphore(get_settings().max_concurrent_plans)


def client_address(request: Request) -> str:
    """The caller's address as best we can tell.

    Behind Render's proxy the socket address is the proxy, so the first entry
    of X-Forwarded-For is used. That header is client-controlled and can be
    forged -- which is exactly why this is a nuisance limit and not a
    security control.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def rate_limited(request: Request) -> None:
    """FastAPI dependency: 429 when one address asks too often."""
    now = time.monotonic()
    address = client_address(request)
    with _lock:
        hits = _seen.get(address)
        if hits is None:
            hits = deque()
            _seen[address] = hits
        _seen.move_to_end(address)
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= MAX_HEAVY_PER_WINDOW:
            retry_after = int(WINDOW_SECONDS - (now - hits[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=(
                    f"More than {MAX_HEAVY_PER_WINDOW} heavy requests in "
                    f"{WINDOW_SECONDS // 60} minutes from this address."
                ),
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        while len(_seen) > MAX_TRACKED_CLIENTS:
            _seen.popitem(last=False)


class heavy_slot:
    """Context manager around a concurrency slot; 429 when none is free."""

    def __enter__(self) -> None:
        if not _slots.acquire(blocking=False):
            raise HTTPException(
                status_code=429,
                detail="The server is busy with other requests; try again in a few seconds.",
                headers={"Retry-After": "5"},
            )

    def __exit__(self, *exc) -> None:
        _slots.release()


def reset_for_tests() -> None:
    with _lock:
        _seen.clear()
