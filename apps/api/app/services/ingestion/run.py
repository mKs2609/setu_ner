"""
The ingestion entry point.

    cd apps/api
    python -m app.services.ingestion.run                 # yesterday's flood report
    python -m app.services.ingestion.run --date 2026-09-07
    python -m app.services.ingestion.run --hazard landslide
    python -m app.services.ingestion.run --backfill 7    # last 7 days, politely
    python -m app.services.ingestion.run --catch-up      # whatever days we still owe

WHY YESTERDAY BY DEFAULT
The report is compiled from what districts submit during the day, so today's
is usually not published until well into the day, and asking for it mostly
returns the empty form. Yesterday is the most recent date that reliably
exists. Pass --date to override.

WHY A MISSING REPORT IS NOT A FAILURE
Plenty of days have no report -- off-season, holidays, or a hazard type with
nothing to report. That exits as `no_data`, which is a normal outcome
recorded in ingest_runs, not an error. Treating it as failure would make
every alerting rule cry wolf for half the year.

SAFE TO SCHEDULE
Runs are idempotent (see store.py), so overlapping or repeated runs cannot
double-count, and a failure never removes previously ingested data.

--catch-up is the mode a scheduler should use. It asks what days are missing
rather than blindly fetching yesterday, so a missed week is recovered instead
of becoming a permanent hole in the history. See schedule.py for which days
get retried and which are left settled.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import IngestRun
from app.db.session import SessionLocal
from app.services.ingestion.http_client import FetchError, PoliteClient
from app.services.ingestion.schedule import plan_catch_up, summarise_plan
from app.services.ingestion.sources import drims
from app.services.ingestion.store import finish_run, start_run, store_observations

# Hazard types confirmed to use the DRIMS disaster-report template, and so
# actually parseable today. The endpoint offers more (rainfall, earthquake,
# fire, ...), but offering them is not the same as being able to read them,
# and a run against an unreadable one now fails loudly rather than silently
# recording nothing.
SUPPORTED_HAZARDS = {"flood", "landslide"}

BASIS = (
    "district-reported daily figures, parsed from the DRIMS Assam "
    "daily hazard report PDF"
)


def ingest_one_day(
    db,
    client: PoliteClient,
    *,
    hazard: str,
    report_date: date,
) -> dict:
    """Fetch, parse and store a single day. Never raises for expected outcomes."""
    run = start_run(
        db,
        source=drims.SOURCE_NAME,
        hazard_type=hazard,
        target_date=report_date,
        source_url=f"{drims.BASE}/download?type={hazard}",
    )

    try:
        fetched = drims.fetch_report(client, hazard, report_date)
    except FetchError as exc:
        # Includes "no report published for this date", which is normal.
        finish_run(db, run, status="no_data", error=str(exc))
        return {"date": report_date, "status": "no_data", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
        finish_run(db, run, status="failed", error=repr(exc))
        return {"date": report_date, "status": "failed", "detail": repr(exc)}

    try:
        printed_date, observations, recognised = drims.parse_report(
            fetched.pdf_bytes, hazard
        )
    except Exception as exc:  # noqa: BLE001
        finish_run(db, run, status="failed", error=f"parse failed: {exc!r}")
        return {"date": report_date, "status": "failed", "detail": f"parse: {exc!r}"}

    if not recognised:
        # The document downloaded fine but is not the template we parse -- the
        # rainfall type returns an IMD bulletin with a different structure.
        # Failing here is the point: recording this as a success with zero rows
        # would look exactly like a genuinely quiet day, forever.
        msg = (
            f"The {hazard} report for {report_date.isoformat()} is not the "
            f"DRIMS disaster-report template this parser understands, so "
            f"nothing was stored. Supported today: "
            f"{', '.join(sorted(SUPPORTED_HAZARDS))}."
        )
        finish_run(db, run, status="failed", error=msg)
        return {"date": report_date, "status": "failed", "detail": msg}

    if printed_date and printed_date != report_date:
        # The portal served a different day than we asked for. Refuse it
        # rather than filing those numbers under the wrong date.
        msg = (
            f"Report says {printed_date.isoformat()} but we asked for "
            f"{report_date.isoformat()}; refusing to store it."
        )
        finish_run(db, run, status="failed", rows_parsed=len(observations), error=msg)
        return {"date": report_date, "status": "failed", "detail": msg}

    written, duplicate = store_observations(
        db,
        run=run,
        source=drims.SOURCE_NAME,
        source_url=fetched.source_url,
        hazard_type=hazard,
        report_date=printed_date or report_date,
        fetched_at=fetched.fetched_at,
        observations=observations,
        basis=BASIS,
    )
    finish_run(
        db,
        run,
        status="success",
        rows_parsed=len(observations),
        rows_written=written,
        rows_duplicate=duplicate,
    )
    return {
        "date": report_date,
        "status": "success",
        "parsed": len(observations),
        "written": written,
        "duplicate": duplicate,
    }


# Ranked worst to best. When a day has several runs, the best outcome wins:
# a success after two failures means we have that day.
_STATUS_RANK = {"failed": 0, "running": 1, "no_data": 2, "success": 3}


def existing_run_status(db, source: str, hazard: str) -> dict[date, str]:
    """Best outcome recorded per target date, for one source and hazard."""
    rows = db.execute(
        select(IngestRun.target_date, IngestRun.status).where(
            IngestRun.source == source,
            IngestRun.hazard_type == hazard,
            IngestRun.target_date.isnot(None),
        )
    ).all()

    best: dict[date, str] = {}
    for target_date, status in rows:
        current = best.get(target_date)
        if current is None or _STATUS_RANK.get(status, -1) > _STATUS_RANK.get(current, -1):
            best[target_date] = status
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest DRIMS Assam hazard reports.")
    parser.add_argument("--hazard", default="flood", choices=sorted(drims.HAZARD_TYPES))
    parser.add_argument("--date", help="YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument(
        "--backfill",
        type=int,
        default=1,
        help="How many consecutive days to fetch, walking backwards.",
    )
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help=(
            "Fetch whatever days are still missing rather than a fixed range. "
            "This is the mode a scheduler should use."
        ),
    )
    args = parser.parse_args(argv)

    client = PoliteClient()
    results = []
    with SessionLocal() as db:
        if args.catch_up:
            existing = existing_run_status(db, drims.SOURCE_NAME, args.hazard)
            days, truncated = plan_catch_up(existing, today=date.today())
            print(summarise_plan(days, truncated, existing))
        elif args.date:
            start = date.fromisoformat(args.date)
            days = [start - timedelta(days=o) for o in range(args.backfill)]
        else:
            start = date.today() - timedelta(days=1)
            days = [start - timedelta(days=o) for o in range(args.backfill)]

        for day in days:
            result = ingest_one_day(db, client, hazard=args.hazard, report_date=day)
            results.append(result)
            print(
                f"{day.isoformat()}  {result['status']:8}  "
                + (
                    f"parsed={result.get('parsed')} written={result.get('written')} "
                    f"duplicate={result.get('duplicate')}"
                    if result["status"] == "success"
                    else str(result.get("detail", ""))[:120]
                )
            )

    failed = [r for r in results if r["status"] == "failed"]
    if not results:
        print("Nothing to do.")
    # A non-zero exit is what a scheduler notices, so it is reserved for real
    # failures. A day with no report published is a normal outcome and exits 0.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
