"""
Working out which days a scheduled run still owes.

WHY CATCH-UP RATHER THAN "FETCH TODAY"
A daily job that only ever fetches yesterday has a quiet failure mode: miss a
week -- laptop off, machine rebooted, network down, nobody ran it -- and that
week is gone forever, because tomorrow's run only asks for tomorrow. The
freshness endpoint would show the data recovering while a permanent hole sat
in the history behind it.

That matters more here than in most pipelines. This history is the only thing
that will eventually unblock the accessibility model, and a model cannot
learn from days nobody ever fetched.

So the scheduled job asks a different question: *what have we not got yet?*

WHICH DAYS GET RETRIED, AND WHICH DO NOT

  success   Never re-fetched. Ingestion is idempotent so it would be harmless,
            but it would also be pointless traffic against a government site.

  failed    Always retried. A failure is our problem -- a timeout, a parse
            error, a portal hiccup -- and the day's report may well still be
            sitting there.

  no_data   Retried only if recent. "No report published for that date" is a
            real answer, but districts submit late and a report can appear a
            day or two after the fact. Past that, accept the gap rather than
            asking the same question forever.

  never run Fetched.

CAPPED ON PURPOSE
A first run against an empty database, or one after a long outage, could
otherwise decide it owes a year of daily fetches and hammer the source in one
go. The plan is capped, and the caller is told when it was truncated so the
gap is visible rather than silently ignored.
"""

from __future__ import annotations

from datetime import date, timedelta

# Most days one scheduled invocation will fetch. Each day costs two requests
# with a crawl delay between them, so this is also roughly a cap on how long
# a single run can occupy the source.
MAX_CATCH_UP_DAYS = 14

# How late a district can submit and still be worth re-asking for.
NO_DATA_RETRY_DAYS = 3

# Statuses that mean "we already have this day, leave it alone".
SETTLED_STATUSES = {"success"}


def plan_catch_up(
    existing: dict[date, str],
    *,
    today: date,
    max_days: int = MAX_CATCH_UP_DAYS,
    no_data_retry_days: int = NO_DATA_RETRY_DAYS,
    lookback_days: int | None = None,
) -> tuple[list[date], bool]:
    """Days still owed, newest first, and whether the plan was truncated.

    `existing` maps a date to the best status already recorded for it.
    Newest-first matters: if the cap bites, the most recent days -- the ones
    an operator actually cares about -- are the ones that get fetched.

    Today is never included. The report is compiled from submissions during
    the day, so asking for it mostly returns an empty form.
    """
    horizon = lookback_days if lookback_days is not None else max_days * 3
    owed: list[date] = []

    for offset in range(1, horizon + 1):
        day = today - timedelta(days=offset)
        status = existing.get(day)

        if status in SETTLED_STATUSES:
            continue
        if status == "no_data" and (today - day).days > no_data_retry_days:
            continue
        if status == "running":
            # A run that never finished. Almost always a killed process; the
            # day is still owed.
            pass

        owed.append(day)

    truncated = len(owed) > max_days
    return owed[:max_days], truncated


def summarise_plan(owed: list[date], truncated: bool, existing: dict[date, str]) -> str:
    """A line a human reading scheduler logs can act on."""
    if not owed:
        return "Nothing owed -- every recent day is already ingested."
    reasons: dict[str, int] = {}
    for day in owed:
        key = existing.get(day) or "never attempted"
        reasons[key] = reasons.get(key, 0) + 1
    breakdown = ", ".join(f"{count} {label}" for label, count in sorted(reasons.items()))
    line = (
        f"{len(owed)} day(s) owed ({breakdown}), "
        f"{owed[-1].isoformat()} to {owed[0].isoformat()}"
    )
    if truncated:
        line += (
            f" -- capped at {MAX_CATCH_UP_DAYS}; older gaps remain and will be "
            f"picked up by later runs"
        )
    return line
