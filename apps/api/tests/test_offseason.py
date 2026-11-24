"""What the model endpoints say once the source stops publishing.

ASDMA stops issuing daily flood reports outside the monsoon -- in 2026 the
last one was 31 October. Two things in the API were written as though the
record always ran up to today, and only showed themselves weeks into the
quiet season.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

ROUTER = Path(__file__).resolve().parents[1] / "app" / "routers" / "model.py"
SOURCE = ROUTER.read_text(encoding="utf-8")


def test_the_replay_window_is_anchored_on_the_record_not_on_today():
    """`days` counted back from today, so the window slid off the end of the
    data once the source stopped. Thirty days after 31 October it would have
    held nothing, and the replay -- the clearest demonstration of the model on
    the whole site -- would have been empty with no explanation."""
    assert "date.today() - timedelta(days=days)" not in SOURCE, (
        "the replay window must not be anchored on today"
    )
    assert "(newest or date.today()) - timedelta(days=days)" in SOURCE


def test_the_window_still_falls_back_when_nothing_is_stored():
    """A fresh database has no newest forecast; the endpoint must still
    answer rather than raise on None."""
    assert "newest or date.today()" in SOURCE


def test_the_district_forecast_says_why_it_is_old():
    """"Stale" covered both "nobody fetched" and "the source published
    nothing". Those need opposite reactions, and the monitoring has drawn the
    distinction since October -- the page had not."""
    assert "_why_old" in SOURCE
    assert "source_published_nothing" in SOURCE
    assert "last_checked" in SOURCE


def test_no_data_is_what_counts_as_the_source_having_nothing():
    """`no_data` means the portal was reached and had nothing for that day --
    a successful conversation. A failure must not read as a quiet source."""
    block = SOURCE[SOURCE.index("def _why_old") : SOURCE.index("def _why_old") + 1600]
    assert 'status == "no_data"' in block, (
        "only no_data should mean the source published nothing"
    )
    assert "failed" not in block.split('status == "no_data"')[1][:200]


def test_the_why_old_helper_reads_the_flood_feed():
    assert 'FLOOD_SOURCE = ("drims_assam_daily_report", "flood")' in SOURCE


def test_the_history_window_logic_in_isolation():
    """The arithmetic itself, without a database."""

    def since(newest: date | None, days: int, today: date) -> date:
        return (newest or today) - timedelta(days=days)

    today = date(2026, 11, 25)
    newest = date(2026, 10, 31)

    # Anchored on the record: a full window regardless of how long it has
    # been quiet.
    assert since(newest, 30, today) == date(2026, 10, 1)
    # Even months later, the window still covers the same real days.
    assert since(newest, 30, date(2027, 3, 1)) == date(2026, 10, 1)
    # Nothing stored at all: fall back to today rather than failing.
    assert since(None, 30, today) == date(2026, 10, 26)


def test_max_history_days_is_still_bounded():
    """The endpoint is public; the window must stay capped."""
    assert re.search(r"MAX_HISTORY_DAYS\s*=\s*60", SOURCE)
    assert "le=MAX_HISTORY_DAYS" in SOURCE
