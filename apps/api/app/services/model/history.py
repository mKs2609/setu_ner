"""
Loading the report history out of the database.

Kept apart from dataset.py so the rules about labels stay pure and testable,
and this file is only the two queries that feed them.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import HazardObservation, IngestRun
from app.services.ingestion.sources import drims
from app.services.model.dataset import USED_METRICS, ReportHistory, build_history

HAZARD = "flood"


def load_history(db) -> ReportHistory:
    # Only days whose report was fetched, recognised and date-checked. A
    # failed or no-data day is unknown and must not supply negatives.
    published = [
        d
        for (d,) in db.execute(
            select(IngestRun.target_date)
            .where(
                IngestRun.source == drims.SOURCE_NAME,
                IngestRun.hazard_type == HAZARD,
                IngestRun.status == "success",
                IngestRun.target_date.isnot(None),
            )
            .distinct()
        )
    ]
    rows = db.execute(
        select(
            HazardObservation.source_document_date,
            HazardObservation.place_name,
            HazardObservation.metric,
            HazardObservation.value_num,
        ).where(
            HazardObservation.source == drims.SOURCE_NAME,
            HazardObservation.hazard_type == HAZARD,
            HazardObservation.metric.in_(sorted(USED_METRICS)),
            HazardObservation.source_document_date.isnot(None),
        )
    ).all()
    return build_history(published, [tuple(r) for r in rows])
