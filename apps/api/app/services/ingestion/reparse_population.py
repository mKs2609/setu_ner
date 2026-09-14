"""
Re-derive stored population and crop figures with the corrected parser.

    cd apps/api
    python -m app.services.ingestion.reparse_population

WHY THIS EXISTS
The population section used to be read by column index. pdfplumber inserts
empty cells that shift columns on some rows, so 31 of 613 stored
`population_affected` values were a component count rather than the total --
Nagaon recorded as 2,534 people instead of 13,463. Found while building
Phase 4 demand estimation (docs/decisions/0011), where the figure is the
quantity being planned for.

HOW
Every observation keeps the source row verbatim in `raw`, so no report is
re-fetched. For each ingest run, the population-section rows are re-parsed
with `drims._parse_population_row`, the old derived rows are removed, and the
re-parsed ones are stored through the normal store path -- so their
`observation_key`s are exactly what a fresh ingest would produce, and a later
re-ingest of the same day is still a no-op.

Each run is replaced in one transaction. Safe to run repeatedly: a second
run re-derives identical rows.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

from sqlalchemy import delete, select

from app.db.models import HazardObservation, IngestRun
from app.db.session import SessionLocal
from app.services.ingestion.districts import normalise_district
from app.services.ingestion.sources import drims
from app.services.ingestion.store import store_observations

METRICS = ("population_affected", "crop_area_submerged", "population_affected_circle")


def reparse(db) -> dict[str, int]:
    rows = db.execute(
        select(HazardObservation).where(
            HazardObservation.metric.in_(METRICS),
            HazardObservation.source == drims.SOURCE_NAME,
            HazardObservation.ingest_run_id.isnot(None),
        )
    ).scalars().all()

    by_run: dict[int, list[HazardObservation]] = defaultdict(list)
    for r in rows:
        if (r.raw or {}).get("section") in drims.POPULATION_SECTIONS:
            by_run[r.ingest_run_id].append(r)

    stats = {"runs": 0, "old_rows": 0, "new_rows": 0, "values_changed": 0}
    for run_id, old in by_run.items():
        run = db.get(IngestRun, run_id)
        template = old[0]

        before = {
            (o.metric, o.place_name): o.value_num
            for o in old
            if o.metric != "population_affected_circle"
        }

        # One source row can have produced several observations; parse each
        # distinct row once.
        source_rows = {json.dumps(o.raw["row"]): o for o in old}
        observations = []
        for o in source_rows.values():
            raw_row = o.raw["row"]
            name = drims._clean(raw_row[1]) if len(raw_row) > 1 else ""
            observations.extend(
                drims._parse_population_row(
                    raw_row, name, normalise_district(name), o.raw.get("hazard", o.hazard_type),
                    raw_row,
                )
            )
        observations = drims._dedupe(observations)

        after = {
            (o.metric, o.place_name): o.value_num
            for o in observations
            if o.metric != "population_affected_circle"
        }
        stats["values_changed"] += sum(1 for k, v in after.items() if before.get(k) != v)

        db.execute(delete(HazardObservation).where(HazardObservation.id.in_([o.id for o in old])))
        # store_observations commits, which makes the delete and the insert
        # one transaction for this run.
        written, _ = store_observations(
            db,
            run=run,
            source=template.source,
            source_url=template.source_url,
            hazard_type=template.hazard_type,
            report_date=template.source_document_date,
            fetched_at=template.fetched_at,
            observations=observations,
            basis=template.basis,
            confidence=template.confidence,
        )
        stats["runs"] += 1
        stats["old_rows"] += len(old)
        stats["new_rows"] += written
    return stats


def main() -> int:
    with SessionLocal() as db:
        stats = reparse(db)
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
