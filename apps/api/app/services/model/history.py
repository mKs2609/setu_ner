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
    history = build_history(published, [tuple(r) for r in rows])
    history.rainfall = load_rainfall(db)
    return history


def load_rainfall(db) -> dict:
    """(district key, day) -> mm, keyed the way the model keys districts.

    Rows are stored under OpenStreetMap's district name; weather.points owns
    the translation to the report's spelling, so it is looked up there rather
    than repeated here.
    """
    from app.services.weather import ingest as rain
    from app.services.weather.points import load_points

    key_for_name = {p.name: key for key, p in load_points().items()}
    out = {}
    for day, place, mm in db.execute(
        select(
            HazardObservation.source_document_date,
            HazardObservation.place_name,
            HazardObservation.value_num,
        ).where(
            HazardObservation.source == rain.SOURCE,
            HazardObservation.hazard_type == rain.HAZARD,
            HazardObservation.metric == rain.METRIC,
            HazardObservation.value_num.isnot(None),
        )
    ):
        key = key_for_name.get(place)
        if key is not None:
            out[(key, day)] = float(mm)
    return out
