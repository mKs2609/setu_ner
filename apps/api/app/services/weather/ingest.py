"""
Store daily rainfall per district, alongside the flood reports.

    cd apps/api
    python -m app.services.weather.ingest --catch-up                 # what the daily job runs
    python -m app.services.weather.ingest --start 2025-05-01 --end 2026-09-20

WHERE IT GOES
`hazard_observations`, as hazard_type "rainfall" -- the table was built
hazard-agnostic for exactly this (see its docstring in db/models.py). Rows
carry no geometry, which keeps them out of every spatial query: damage
matching, scenario conditions and field-report corroboration all select
`WHERE geometry IS NOT NULL`. They get their own line in /hazards/freshness.

SAME RULES AS THE FLOOD REPORTS
Every day is an `ingest_runs` row written before the fetch, so a killed run
is visible and still owed. Catch-up uses the same planner (schedule.py). A
day NASA has not published yet is `no_data`, retried for three days, which
is two more than the Late product needs. Re-running a day writes nothing
twice (observation_key is unique).

A district whose every cell is missing that day is skipped, not written as
zero -- see imerg.district_rainfall.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.services.ingestion.districts import normalise_district
from app.services.ingestion.run import existing_run_status
from app.services.ingestion.schedule import plan_catch_up, summarise_plan
from app.services.ingestion.sources.drims import Observation
from app.services.ingestion.store import finish_run, start_run, store_observations
from app.services.weather.imerg import (
    ASSAM_BOX,
    OPENDAP_DIR,
    EarthdataAuthError,
    ImergClient,
    district_rainfall,
)
from app.services.weather.points import load_points

SOURCE = "nasa_gpm_imerg_late"
HAZARD = "rainfall"
METRIC = "rainfall_mm"
UNIT = "mm/day"
BASIS = (
    "NASA GPM IMERG Late Run V07 daily precipitation (GPM_3IMERGDL), 0.1 degree "
    "grid, averaged over the cells in a box the size of the district"
)
# A satellite estimate: good at whether and roughly how much it rained over a
# district-sized area, weaker for any single point. Same tier as the reports.
CONFIDENCE = "medium"


def observations_for(grid, points) -> tuple[list[Observation], list[str]]:
    """One observation per district with any valid cell; the rest listed."""
    out: list[Observation] = []
    missing: list[str] = []
    for key, point in sorted(points.items()):
        mm = district_rainfall(grid, point)
        if mm is None:
            missing.append(key)
            continue
        out.append(
            Observation(
                metric=METRIC,
                value_num=round(mm, 2),
                value_text=None,
                unit=UNIT,
                place_name=point.name,
                # From the matched key, not OSM's name: OSM calls one district
                # "Hailakandi district", which the corridor matcher rejects.
                district=normalise_district(key),
                raw={
                    "district_key": key,
                    "centre": [point.lon, point.lat],
                    "half_width_deg": [point.half_lon, point.half_lat],
                },
            )
        )
    return out, missing


def ingest_one_day(db, imerg: ImergClient, day: date) -> dict:
    url = OPENDAP_DIR.format(year=day.year, month=day.month)
    run = start_run(db, source=SOURCE, hazard_type=HAZARD, target_date=day, source_url=url)
    try:
        grid = imerg.grid_for(day, ASSAM_BOX)
        if grid is None:
            finish_run(db, run, status="no_data", error="not published yet")
            return {"status": "no_data", "detail": "not published yet"}
        observations, missing = observations_for(grid, load_points())
        written, duplicate = store_observations(
            db,
            run=run,
            source=SOURCE,
            source_url=url + (imerg.filename_for(day) or ""),
            hazard_type=HAZARD,
            report_date=day,
            fetched_at=datetime.now(timezone.utc),
            observations=observations,
            basis=BASIS,
            confidence=CONFIDENCE,
        )
        finish_run(
            db, run,
            status="success",
            rows_parsed=len(observations),
            rows_written=written,
            rows_duplicate=duplicate,
            error=f"no valid cells for: {', '.join(missing)}" if missing else None,
        )
        return {"status": "success", "parsed": len(observations), "written": written,
                "duplicate": duplicate, "missing": missing}
    except EarthdataAuthError:
        finish_run(db, run, status="failed", error="Earthdata credentials rejected")
        raise
    except Exception as exc:  # noqa: BLE001 -- recorded on the run, then reported
        finish_run(db, run, status="failed", error=f"{type(exc).__name__}: {exc}")
        return {"status": "failed", "detail": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest daily district rainfall (NASA IMERG).")
    parser.add_argument("--catch-up", action="store_true", help="Fetch the days still owed.")
    parser.add_argument("--start", help="YYYY-MM-DD, first day of an explicit range.")
    parser.add_argument("--end", help="YYYY-MM-DD, last day of an explicit range (default yesterday).")
    args = parser.parse_args(argv)

    try:
        imerg = ImergClient()
    except EarthdataAuthError as exc:
        print(f"FAILED: {exc}")
        return 1

    with SessionLocal() as db:
        if args.catch_up:
            existing = existing_run_status(db, SOURCE, HAZARD)
            days, truncated = plan_catch_up(existing, today=date.today())
            print(summarise_plan(days, truncated, existing))
        elif args.start:
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
            existing = existing_run_status(db, SOURCE, HAZARD)
            # A range is still polite about what it already has.
            days = [
                start + timedelta(days=n)
                for n in range((end - start).days + 1)
                if existing.get(start + timedelta(days=n)) != "success"
            ]
            print(f"{len(days)} day(s) to fetch between {start} and {end}")
        else:
            parser.error("pass --catch-up or --start")

        results = []
        for day in days:
            try:
                r = ingest_one_day(db, imerg, day)
            except EarthdataAuthError as exc:
                print(f"FAILED: {exc}")
                return 1
            results.append(r)
            detail = (
                f"districts={r['parsed']} written={r['written']} duplicate={r['duplicate']}"
                + (f" missing={len(r['missing'])}" if r.get("missing") else "")
                if r["status"] == "success"
                else r.get("detail", "")
            )
            print(f"{day.isoformat()}  {r['status']:8}  {detail}", flush=True)

    failed = [r for r in results if r["status"] == "failed"]
    if not results:
        print("Nothing to do.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
