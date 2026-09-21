"""
Liveness and readiness.

    GET /api/v1/health         the process is up (cheap; for restart probes)
    GET /api/v1/health/ready   it can actually serve (for deploy health checks)

Readiness is what a hosting platform should gate traffic on. A freshly
deployed API can be "up" while the database is unreachable, the PostGIS
extension missing, a migration not applied, the model artifacts absent from
the image, or the daily job silently dead for a week. Each of those is checked
and named, so a failed deploy says why instead of serving errors.

Data staleness is reported but does not fail readiness: an API serving
week-old forecasts should still answer, with the forecast endpoints already
marking them stale. It is surfaced here so monitoring can alert on it.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.ingestion.sources import drims
from app.services.logistics import gazetteer
from app.services.model import district_model as dm
from app.services.model import score as scoring
from app.services.weather import ingest as rainfall
from app.services.weather import points as rainfall_points

router = APIRouter()

REQUIRED_TABLES = (
    "roads", "hazard_observations", "ingest_runs", "field_reports", "reporters",
    "district_flood_forecasts", "road_damage_matches", "recommendations",
    "recommendation_overrides", "satellite_acquisitions",
)
REQUIRED_ROAD_COLUMNS = ("elevation_m", "accessibility_model_version", "current_accessibility_as_of")


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _latest_success(db, source: str, hazard_type: str) -> date | None:
    return db.execute(
        text(
            "SELECT max(target_date) FROM ingest_runs "
            "WHERE status = 'success' AND source = :source AND hazard_type = :hazard"
        ),
        {"source": source, "hazard": hazard_type},
    ).scalar()


@router.get("/health/ready")
def readiness():
    checks: dict[str, dict] = {}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            checks["database"] = {"ok": True}

            postgis = db.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            ).scalar()
            checks["postgis"] = {"ok": postgis is not None, "version": postgis}

            present = {
                r[0] for r in db.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
                )
            }
            missing = [t for t in REQUIRED_TABLES if t not in present]
            checks["tables"] = {"ok": not missing, "missing": missing}

            cols = {
                r[0] for r in db.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name = 'roads'")
                )
            }
            missing_cols = [c for c in REQUIRED_ROAD_COLUMNS if c not in cols]
            checks["migrations"] = {
                "ok": not missing_cols,
                "missing_road_columns": missing_cols,
                "hint": "run `python -m app.db.migrate`" if missing_cols else None,
            }

            if "roads" in present:
                roads = db.execute(text("SELECT count(*) FROM roads")).scalar()
                checks["road_graph_data"] = {"ok": roads > 0, "roads": roads}

            if "ingest_runs" in present:
                # Per source. Counting any source's runs would let a fresh
                # rainfall day hide a dead report feed -- the one failure
                # this check exists to show.
                latest = _latest_success(db, drims.SOURCE_NAME, "flood")
                age = (date.today() - latest).days if latest else None
                checks["data_freshness"] = {
                    "ok": True,  # informational; see module docstring
                    "latest_report": latest.isoformat() if latest else None,
                    "age_days": age,
                    "stale": age is None or age > scoring.MAX_STALE_DAYS,
                }
                rain = _latest_success(db, rainfall.SOURCE, rainfall.HAZARD)
                rain_age = (date.today() - rain).days if rain else None
                checks["rainfall_freshness"] = {
                    # Informational too: without rain the scorer serves
                    # persistence and says so, rather than failing.
                    "ok": True,
                    "latest_day": rain.isoformat() if rain else None,
                    "age_days": rain_age,
                    "stale": rain_age is None or rain_age > scoring.MAX_STALE_DAYS,
                }
    except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
        checks["database"] = {"ok": False, "error": type(exc).__name__}

    artifacts = {h: dm.load(h) is not None for h in dm.HORIZONS}
    checks["model_artifacts"] = {"ok": all(artifacts.values()), "present": artifacts}
    checks["gazetteer"] = {"ok": gazetteer.GAZETTEER_PATH.exists()}
    # The model reads rainfall per district through these boxes.
    checks["rainfall_points"] = {"ok": rainfall_points.POINTS_PATH.exists()}

    ready = all(c.get("ok") for c in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "checks": checks},
    )
