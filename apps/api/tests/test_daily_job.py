"""The daily job wakes the database before the first step pays for it.

12 and 13 November 2026: flood ingestion failed both mornings with
`SSL error: unexpected eof while reading` from the Neon pooler, after 225s
and 148s. Landslide, seconds later, succeeded both times -- the database had
woken up by then. Neon suspends compute when idle, nothing retried, and so
whichever step happened to run first simply lost.

The visible symptom was two days of no flood fetches at all, which the
deployment watcher correctly reported as *we* stopped asking rather than the
source going quiet.
"""

from __future__ import annotations

import pytest

from app.jobs import daily


class _Boom(Exception):
    """Stands in for psycopg2.OperationalError without importing it."""


def _session_factory(failures: int, exc: type[Exception] = _Boom):
    """A SessionLocal that raises `failures` times, then works."""
    state = {"calls": 0}

    class _Session:
        def __enter__(self):
            state["calls"] += 1
            if state["calls"] <= failures:
                raise exc("SSL error: unexpected eof while reading")
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _stmt):
            return None

    return _Session, state


@pytest.fixture
def no_sleep(monkeypatch):
    """The real delays total ~37s; these tests should not."""
    monkeypatch.setattr(daily.time, "sleep", lambda _s: None)


def _patch_session(monkeypatch, factory):
    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "SessionLocal", factory)


def test_a_database_that_answers_at_once_is_not_retried(monkeypatch, no_sleep):
    factory, state = _session_factory(failures=0)
    _patch_session(monkeypatch, factory)

    awake, why = daily.database_awake()

    assert awake is True
    assert "immediately" in why
    assert state["calls"] == 1


def test_a_sleeping_database_is_woken_rather_than_failed(monkeypatch, no_sleep):
    """The real case: refused twice while Neon wakes, then fine."""
    factory, state = _session_factory(failures=2)
    _patch_session(monkeypatch, factory)

    awake, why = daily.database_awake()

    assert awake is True, "a cold start must not be reported as an outage"
    assert "attempt 3" in why
    assert state["calls"] == 3


def test_it_gives_up_eventually_and_reports_the_reason(monkeypatch, no_sleep):
    factory, state = _session_factory(failures=99)
    _patch_session(monkeypatch, factory)

    awake, why = daily.database_awake()

    assert awake is False
    assert "SSL error" in why, "the operator needs the actual reason"
    # One attempt per delay, plus the final one with no delay after it.
    assert state["calls"] == len(daily.DB_WAKE_DELAYS_S) + 1


def test_the_delays_are_short_enough_to_report_a_real_outage_promptly():
    """Long enough for a cold start, short enough not to hang the morning."""
    total = sum(daily.DB_WAKE_DELAYS_S)
    assert 20 <= total <= 120, f"{total}s of patience is the wrong order"
    assert list(daily.DB_WAKE_DELAYS_S) == sorted(daily.DB_WAKE_DELAYS_S), (
        "delays should back off, not jitter"
    )


def test_every_step_needs_the_database_so_none_run_without_it(monkeypatch, no_sleep):
    """A dead database must not be answered with five steps failing slowly."""
    factory, _ = _session_factory(failures=99)
    _patch_session(monkeypatch, factory)

    ran: list[str] = []
    monkeypatch.setattr(
        daily.subprocess,
        "run",
        lambda *a, **k: ran.append(a) or pytest.fail("a step ran without a database"),
    )
    # If the portal were probed first, a dead database would still cost a
    # network round trip to ASDMA before anything was reported.
    monkeypatch.setattr(
        daily, "portal_reachable", lambda *a, **k: pytest.fail("probed the portal first")
    )

    assert daily.main() == 1
    assert ran == []
