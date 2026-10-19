"""
Tests for scheduled catch-up.

All of this runs without a database or network. The planning rule is a pure
function on purpose: deciding which days a scheduler still owes is exactly
the kind of logic that is easy to get subtly wrong and impossible to notice,
because the symptom is a quiet hole in history rather than an error.
"""

from datetime import date, datetime, timedelta

from app.services.ingestion.schedule import (
    MAX_CATCH_UP_DAYS,
    NO_DATA_RETRY_DAYS,
    plan_catch_up,
    summarise_plan,
)

TODAY = date(2026, 9, 11)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def test_an_empty_history_owes_everything_up_to_the_cap():
    owed, truncated = plan_catch_up({}, today=TODAY)
    assert len(owed) == MAX_CATCH_UP_DAYS
    assert truncated is True


def test_today_is_never_fetched():
    """The report is compiled from submissions during the day, so asking for
    today mostly returns an empty form."""
    owed, _ = plan_catch_up({}, today=TODAY)
    assert TODAY not in owed


def test_newest_days_are_fetched_first_when_the_cap_bites():
    """If the cap bites, the days an operator actually cares about are the
    recent ones."""
    owed, truncated = plan_catch_up({}, today=TODAY, max_days=3)
    assert owed == [days_ago(1), days_ago(2), days_ago(3)]
    assert truncated is True


def test_a_successful_day_is_never_refetched():
    """Idempotency would make it harmless, but it is still pointless traffic
    against a government site."""
    existing = {days_ago(1): "success", days_ago(2): "success"}
    owed, _ = plan_catch_up(existing, today=TODAY, max_days=5)
    assert days_ago(1) not in owed
    assert days_ago(2) not in owed
    assert days_ago(3) in owed


def test_a_failed_day_is_always_retried():
    """A failure is our problem -- a timeout, a parse error -- and the day's
    report may well still be sitting there."""
    existing = {days_ago(5): "failed"}
    owed, _ = plan_catch_up(existing, today=TODAY, max_days=10)
    assert days_ago(5) in owed


def test_a_recent_no_data_day_is_retried_because_districts_submit_late():
    existing = {days_ago(1): "no_data"}
    owed, _ = plan_catch_up(existing, today=TODAY, max_days=10)
    assert days_ago(1) in owed


def test_an_old_no_data_day_is_left_alone():
    """'No report published' is a real answer. Past the late-submission
    window, accept the gap rather than asking forever."""
    old = days_ago(NO_DATA_RETRY_DAYS + 2)
    existing = {old: "no_data"}
    owed, _ = plan_catch_up(existing, today=TODAY, max_days=20)
    assert old not in owed


def test_the_no_data_boundary_is_inclusive():
    boundary = days_ago(NO_DATA_RETRY_DAYS)
    owed, _ = plan_catch_up({boundary: "no_data"}, today=TODAY, max_days=20)
    assert boundary in owed, "a day exactly at the retry limit is still retried"


def test_an_unfinished_run_leaves_the_day_owed():
    """A 'running' row is almost always a killed process, not a run in
    flight. Treating it as done would lose the day permanently."""
    existing = {days_ago(2): "running"}
    owed, _ = plan_catch_up(existing, today=TODAY, max_days=5)
    assert days_ago(2) in owed


def test_a_fully_ingested_recent_history_owes_nothing():
    existing = {days_ago(n): "success" for n in range(1, 60)}
    owed, truncated = plan_catch_up(existing, today=TODAY)
    assert owed == []
    assert truncated is False


def test_a_gap_in_the_middle_is_recovered():
    """The whole point: a missed stretch is not lost just because newer days
    succeeded afterwards."""
    # History must cover the whole scan horizon, or days beyond it are
    # legitimately owed too and the assertion is about the wrong thing.
    existing = {days_ago(n): "success" for n in range(1, 21)}
    for n in (5, 6, 7):
        del existing[days_ago(n)]
    owed, truncated = plan_catch_up(
        existing, today=TODAY, max_days=10, lookback_days=20
    )
    assert sorted(owed) == sorted([days_ago(5), days_ago(6), days_ago(7)])
    assert truncated is False


def test_truncation_is_reported_not_hidden():
    """An operator has to be able to see that older gaps remain."""
    owed, truncated = plan_catch_up({}, today=TODAY, max_days=2)
    assert truncated is True
    assert "capped" in summarise_plan(owed, truncated, {})


def test_summary_names_why_each_day_is_owed():
    existing = {days_ago(1): "failed"}
    owed, truncated = plan_catch_up(existing, today=TODAY, max_days=3)
    line = summarise_plan(owed, truncated, existing)
    assert "failed" in line
    assert "never attempted" in line


def test_summary_says_so_when_nothing_is_owed():
    assert "Nothing owed" in summarise_plan([], False, {})


class _Row(tuple):
    """A (target_date, status, started_at) row, as the query returns them."""


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _stmt):
        rows = self._rows

        class R:
            @staticmethod
            def all():
                return rows

        return R()


def _status(rows):
    from app.services.ingestion.run import existing_run_status

    return existing_run_status(_FakeDb(rows), "src", "flood")


def test_a_success_settles_a_day_however_many_failures_came_first():
    day = date(2026, 10, 9)
    assert _status([
        (day, "failed", datetime(2026, 10, 11, 2, 0)),
        (day, "success", datetime(2026, 10, 12, 2, 0)),
        (day, "failed", datetime(2026, 10, 13, 2, 0)),
    ])[day] == "success"


def test_a_later_failure_outranks_an_earlier_no_data():
    """13 Oct 2026, from production: 9 October rainfall was lost for good.

    It was asked for before IMERG had published it (`no_data`), then failed
    twice against a NASA outage. Taking the best outcome gave `no_data`, which
    plan_catch_up writes off after three days -- so the day was dropped while
    its most recent news was a hard failure.
    """
    day = date(2026, 10, 9)
    assert _status([
        (day, "no_data", datetime(2026, 10, 10, 2, 0)),
        (day, "failed", datetime(2026, 10, 11, 2, 0)),
        (day, "failed", datetime(2026, 10, 12, 2, 0)),
    ])[day] == "failed"


def test_that_day_is_then_still_owed_four_days_later():
    """The point of the fix: the plan must still ask for it."""
    day = date(2026, 10, 9)
    existing = _status([
        (day, "no_data", datetime(2026, 10, 10, 2, 0)),
        (day, "failed", datetime(2026, 10, 11, 2, 0)),
        (day, "failed", datetime(2026, 10, 12, 2, 0)),
    ])
    owed, _ = plan_catch_up(existing, today=date(2026, 10, 13))
    assert day in owed


def test_a_rejected_day_is_retried_briefly_then_left_alone():
    """16 Oct 2026, from production: ASDMA served the report printed
    2025-05-16 whenever we asked for 2026-10-16. The date guard refused it.

    Recorded as `failed` it was re-asked every morning for the identical wrong
    document, and the watcher emailed about it four times a day. Two days of
    retries covers a transient publishing glitch; after that it needs a person,
    not a scheduler.
    """
    day = date(2026, 10, 16)
    existing = {day: "rejected"}

    owed, _ = plan_catch_up(existing, today=date(2026, 10, 17))
    assert day in owed, "a fresh rejection is still worth one more try"

    owed, _ = plan_catch_up(existing, today=date(2026, 10, 18))
    assert day in owed, "the boundary is inclusive"

    owed, _ = plan_catch_up(existing, today=date(2026, 10, 19))
    assert day not in owed, "past the window it must stop asking"


def test_a_rejected_day_is_not_treated_as_settled():
    """It is not a success. The day is genuinely missing, and anything that
    reports coverage must not count it as held."""
    from app.services.ingestion.schedule import SETTLED_STATUSES

    assert "rejected" not in SETTLED_STATUSES
    assert "success" in SETTLED_STATUSES


def test_a_later_success_still_wins_over_a_rejection():
    """If the source is fixed and the day is refetched, that settles it."""
    day = date(2026, 10, 16)
    assert _status([
        (day, "rejected", datetime(2026, 10, 17, 2, 0)),
        (day, "success", datetime(2026, 10, 25, 2, 0)),
    ])[day] == "success"


def test_a_genuine_no_data_is_still_dropped_after_the_retry_window():
    """The opposite case must keep working: a day the source really has
    nothing for is not asked about forever."""
    day = date(2026, 10, 9)
    existing = _status([
        (day, "no_data", datetime(2026, 10, 10, 2, 0)),
        (day, "no_data", datetime(2026, 10, 12, 2, 0)),
    ])
    owed, _ = plan_catch_up(existing, today=date(2026, 10, 13))
    assert day not in owed
