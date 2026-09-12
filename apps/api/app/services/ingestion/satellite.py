"""
Recording which radar passes covered the corridor.

    cd apps/api
    python -m app.services.ingestion.satellite
    python -m app.services.ingestion.satellite --days 90

Idempotent on the Copernicus product id, so re-running is a no-op -- same
discipline as the DRIMS ingestion in 0004, and for the same reason: anything
that might be scheduled has to survive being run twice.

This stores coverage, not flood extent. See sources/copernicus.py for why
that boundary is where it is.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models import SatelliteAcquisition
from app.db.session import SessionLocal
from app.services.ingestion.http_client import PoliteClient
from app.services.ingestion.sources import copernicus as cop


def store(db, acquisitions: list[cop.Acquisition]) -> tuple[int, int]:
    """Insert what is new. Returns (written, already_known)."""
    if not acquisitions:
        return 0, 0

    ids = [a.product_id for a in acquisitions]
    known = {
        pid
        for (pid,) in db.execute(
            select(SatelliteAcquisition.product_id).where(
                SatelliteAcquisition.product_id.in_(ids)
            )
        )
    }

    written = 0
    now = datetime.now(timezone.utc)
    for acq in acquisitions:
        if acq.product_id in known:
            continue
        db.add(
            SatelliteAcquisition(
                product_id=acq.product_id,
                name=acq.name,
                mission=acq.mission,
                product_type=acq.product_type,
                acquired_at=acq.acquired_at,
                size_bytes=acq.size_bytes,
                online=acq.online,
                footprint=(
                    func.ST_SetSRID(func.ST_GeomFromText(acq.footprint_wkt), 4326)
                    if acq.footprint_wkt
                    else None
                ),
                source=cop.SOURCE_NAME,
                source_url=cop.CATALOGUE,
                fetched_at=now,
            )
        )
        known.add(acq.product_id)
        written += 1

    db.commit()
    return written, len(acquisitions) - written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record Sentinel-1 coverage of the corridor.")
    parser.add_argument("--days", type=int, default=30, help="How far back to search.")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    client = PoliteClient()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    try:
        acquisitions = cop.search(client, since=since, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"catalogue search failed: {exc}")
        return 1

    with SessionLocal() as db:
        written, known = store(db, acquisitions)

    print(
        f"{len(acquisitions)} usable scene(s) in the last {args.days} days: "
        f"{written} new, {known} already recorded"
    )
    if acquisitions:
        newest = max(a.acquired_at for a in acquisitions)
        age_h = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
        print(f"most recent pass: {newest.isoformat()} ({age_h:.0f} h ago)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
