"""
SetuNER API entrypoint.

Every router below is mounted under /api/v1 and backed by real data: the
daily government report, satellite rainfall, the road graph in PostGIS, and
the forecasts the scoring job writes each morning.

Run locally:
    cd apps/api
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Then visit http://localhost:8000/docs for interactive API docs.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.routers import (
    health,
    roads,
    hazards,
    accessibility,
    logistics,
    scenarios,
    recommendations,
    field_reports,
    roads_geojson,
    model,
)

settings = get_settings()

# Refuse to serve an unsafe production configuration (see app/config.py).
if settings.is_production:
    _problems = settings.production_problems()
    if _problems:
        raise RuntimeError(
            "Refusing to start in production:\n  - " + "\n  - ".join(_problems)
        )

# Tag order here is the order the groups appear in /docs, and the descriptions
# are what a reader sees before any endpoint. Roughly the order you would use
# them in: what the roads are, what is forecast, what to send, who said so.
TAGS = [
    {"name": "roads", "description":
        "The road graph itself: 110,266 OpenStreetMap segments with length, class, "
        "terrain and baseline travel time. `/roads/geojson` is the map layer, built "
        "inside PostGIS and gzipped."},
    {"name": "accessibility", "description":
        "The forecast per road, and why. A score is the district flood probability "
        "multiplied by a terrain exposure prior — the prior is a stated assumption, "
        "not a fitted result, and the explanation endpoint says so every time."},
    {"name": "model", "description":
        "The model's own report card: how it was trained and validated, what it "
        "scored on a held-out season against persistence and climatology, whether "
        "its probabilities are calibrated, and how it is doing on live forecasts. "
        "Where it loses to its baseline, the baseline is what gets served."},
    {"name": "hazards", "description":
        "Raw observations as ingested, and the freshness of each feed. Ingestion "
        "only ever inserts, so a source going down shows as rising age plus a "
        "failed run — never as an empty result that could read as an all-clear."},
    {"name": "logistics", "description":
        "Demand from relief-camp populations, and a delivery plan over the roads "
        "the forecast expects to survive. The optimiser maximises coverage first, "
        "then minimises the worst shortfall, then truck-hours — so a plan cannot "
        "trade coverage for convenience — and reports its binding constraint."},
    {"name": "scenarios", "description":
        "What-if routing: close a road or a bridge and compare. Absolute travel "
        "times are modelled from assumed speeds, so the engine leads with the "
        "difference between two routes on the same graph, where that assumption "
        "largely cancels."},
    {"name": "field-reports", "description":
        "Reports from the ground, unauthenticated by design to keep the barrier "
        "low. They are corroborated against the official damage record and never "
        "overwrite a score; independent evidence can support a report but is not "
        "allowed to count against one."},
    {"name": "recommendations", "description":
        "The audit trail. Every saved plan keeps its inputs, model versions and "
        "the data date it was built from, so an old decision can be read back as "
        "it was made rather than recomputed with today's model."},
    {"name": "health", "description":
        "Liveness and readiness. Readiness reports staleness but never fails on "
        "it, because the host gates traffic on this endpoint and a restart fixes "
        "nothing about old data — monitoring reads the flags instead."},
]

app = FastAPI(
    title="SetuNER — Road Accessibility & Relief Logistics API",
    description=(
        "Forecasts which roads in the Barak Valley corridor of Assam will still "
        "be passable tomorrow, and plans relief deliveries over the ones that "
        "survive.\n\n"
        "Every figure carries the date of the data behind it. Reads are open; "
        "writes that enter the audit trail need an operator token. The service "
        "runs on a free instance that sleeps when idle, so the first request "
        "after a quiet spell can take up to a minute."
    ),
    version="0.1.0",
    openapi_tags=TAGS,
)

# Road maps are megabytes of highly repetitive JSON; gzip cuts them several
# times over. Level 5 rather than 9: most of the size win for much less CPU,
# which matters on a free instance's fraction of a core.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(roads_geojson.router, prefix="/api/v1/roads", tags=["roads"])
app.include_router(roads.router, prefix="/api/v1/roads", tags=["roads"])
app.include_router(hazards.router, prefix="/api/v1/hazards", tags=["hazards"])
app.include_router(accessibility.router, prefix="/api/v1/accessibility", tags=["accessibility"])
app.include_router(logistics.router, prefix="/api/v1/logistics", tags=["logistics"])
app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["scenarios"])
app.include_router(recommendations.router, prefix="/api/v1/recommendations", tags=["recommendations"])
app.include_router(field_reports.router, prefix="/api/v1/field-reports", tags=["field-reports"])
app.include_router(model.router, prefix="/api/v1/model", tags=["model"])


@app.get("/")
def root():
    """Liveness only: the process is up and serving.

    It deliberately touches nothing else, so it stays cheap and cannot fail for
    a reason that is not about this process. For anything real, use
    `/api/v1/health/ready`.
    """
    return {
        "service": "setuner-api",
        "status": "ok",
        "docs": "/docs",
    }
