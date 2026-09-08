"""
Persisting hazard observations, and the bookkeeping that makes ingestion
safe to run unattended.

THE SAFETY PROPERTIES THIS FILE IS RESPONSIBLE FOR

  Never destructive.   Ingestion only ever inserts. It does not delete, blank
                       or overwrite earlier observations. A source that goes
                       down therefore surfaces as *stale data plus a failed
                       run*, never as an empty map that reads like "no
                       flooding anywhere".

  Idempotent.          Every observation carries a deterministic
                       `observation_key`. Re-running the same day is a no-op,
                       so a retry, a cron overlap or a manual re-run cannot
                       double-count. This is what makes the job safe to
                       schedule.

  Auditable.           Every row records which run wrote it, from which URL,
                       with the source's own row kept in `raw`.

  Honest about dates.  The report's printed date is compared with the date we
                       asked for. A mismatch fails the run rather than
                       silently filing yesterday's numbers under today.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import HazardObservation, IngestRun
from app.services.ingestion.sources.drims import Observation

# Everything from this source is a district-level administrative report:
# authoritative for what was reported, but coarse in space and reported once
# a day. "medium" says exactly that -- it is better than the annual
# retrospective the baseline score uses, and weaker than a direct measurement.
DEFAULT_CONFIDENCE = "medium"


def observation_key(
    source: str,
    hazard_type: str,
    report_date: date,
    obs: Observation,
) -> str:
    """A stable identity for one fact, so re-ingesting cannot duplicate it.

    Includes the raw row: several damage points can share a district and
    metric on the same day, and they are only distinguishable by their detail.
    """
    payload = json.dumps(
        [
            source,
            hazard_type,
            report_date.isoformat(),
            obs.metric,
            obs.place_name,
            obs.value_num,
            obs.value_text,
            obs.lon,
            obs.lat,
            obs.raw.get("row"),
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def start_run(
    db: Session,
    *,
    source: str,
    hazard_type: str,
    target_date: date,
    source_url: str | None = None,
) -> IngestRun:
    """Record the attempt before doing anything that can fail or hang."""
    run = IngestRun(
        source=source,
        hazard_type=hazard_type,
        started_at=datetime.now(timezone.utc),
        status="running",
        target_date=target_date,
        source_url=source_url,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(
    db: Session,
    run: IngestRun,
    *,
    status: str,
    rows_parsed: int = 0,
    rows_written: int = 0,
    rows_duplicate: int = 0,
    error: str | None = None,
) -> IngestRun:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.rows_parsed = rows_parsed
    run.rows_written = rows_written
    run.rows_duplicate = rows_duplicate
    # Truncated: a stack trace belongs in logs, a summary belongs in the row.
    run.error = (error or None) and error[:4000]
    db.commit()
    db.refresh(run)
    return run


def store_observations(
    db: Session,
    *,
    run: IngestRun,
    source: str,
    source_url: str,
    hazard_type: str,
    report_date: date,
    fetched_at: datetime,
    observations: list[Observation],
    basis: str,
    confidence: str = DEFAULT_CONFIDENCE,
) -> tuple[int, int]:
    """Insert what is new. Returns (written, skipped_as_duplicate)."""
    keys = [observation_key(source, hazard_type, report_date, o) for o in observations]
    existing = set()
    if keys:
        existing = {
            k
            for (k,) in db.execute(
                select(HazardObservation.observation_key).where(
                    HazardObservation.observation_key.in_(keys)
                )
            )
        }

    written = 0
    duplicate = 0
    observed_at = datetime(
        report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc
    )

    for obs, key in zip(observations, keys):
        if key in existing:
            duplicate += 1
            continue
        row = HazardObservation(
            hazard_type=hazard_type,
            metric=obs.metric,
            value_num=obs.value_num,
            value_text=obs.value_text,
            unit=obs.unit,
            place_name=obs.place_name,
            district=obs.district,
            geometry=(
                func.ST_SetSRID(func.ST_MakePoint(obs.lon, obs.lat), 4326)
                if obs.lon is not None and obs.lat is not None
                else None
            ),
            observed_at=observed_at,
            fetched_at=fetched_at,
            source=source,
            source_url=source_url,
            source_document_date=report_date,
            basis=basis,
            confidence=confidence,
            raw=obs.raw,
            observation_key=key,
            ingest_run_id=run.id,
        )
        db.add(row)
        existing.add(key)  # guards duplicates inside a single batch too
        written += 1

    db.commit()
    return written, duplicate
