"""
SetuNER API entrypoint.

This is a real, runnable FastAPI app -- not a mockup. Every router below is
currently a stub that returns placeholder data, but the app boots, the
health check works, and the shape is what the rest of the build fills in.

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
    regions,
    roads,
    hazards,
    accessibility,
    logistics,
    scenarios,
    recommendations,
    field_reports,
    public,
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

app = FastAPI(
    title="SetuNER — Road Accessibility & Relief Logistics API",
    description=(
        "Dynamic accessibility forecasting and logistics optimization for "
        "the North Eastern Region. See /docs for interactive API reference."
    ),
    version="0.1.0",
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
app.include_router(regions.router, prefix="/api/v1/regions", tags=["regions"])
app.include_router(roads_geojson.router, prefix="/api/v1/roads", tags=["roads"])
app.include_router(roads.router, prefix="/api/v1/roads", tags=["roads"])
app.include_router(hazards.router, prefix="/api/v1/hazards", tags=["hazards"])
app.include_router(accessibility.router, prefix="/api/v1/accessibility", tags=["accessibility"])
app.include_router(logistics.router, prefix="/api/v1/logistics", tags=["logistics"])
app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["scenarios"])
app.include_router(recommendations.router, prefix="/api/v1/recommendations", tags=["recommendations"])
app.include_router(field_reports.router, prefix="/api/v1/field-reports", tags=["field-reports"])
app.include_router(model.router, prefix="/api/v1/model", tags=["model"])
app.include_router(public.router, prefix="/api/v1/public", tags=["public"])


@app.get("/")
def root():
    return {
        "service": "setuner-api",
        "status": "ok",
        "docs": "/docs",
    }
