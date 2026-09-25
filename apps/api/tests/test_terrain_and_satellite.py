"""
Tests for terrain sampling and satellite coverage.

The parsing half runs without network or database. The terrain half checks
the data actually landed and is physically sensible -- elevation is one of
the few things in this project where a wrong answer is obvious if you look,
and completely invisible if you don't.
"""


import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ingestion.sources import copernicus as cop

client = TestClient(app)


# ---------------------------------------------------------------------------
# Catalogue parsing -- no network
# ---------------------------------------------------------------------------


def test_grd_product_type_is_recognised():
    name = "S1D_IW_GRDH_1SDV_20260908T234657_20260908T234722_004493_008588"
    assert cop._product_type(name) == "IW_GRDH_1S"


def test_slc_and_raw_are_not_treated_as_grd():
    """SLC and RAW are listed for the same pass and are not what a flood
    pipeline would use. Storing them would be noise, not coverage."""
    for name in (
        "S1D_IW_SLC__1SDV_20260908T234655_20260908T234723_004493_008588",
        "S1D_IW_RAW__0SDV_20260908T234653_20260908T234726_004493_008588",
    ):
        assert cop._product_type(name) not in cop.USEFUL_PRODUCT_TYPES


def test_a_nonsense_name_yields_no_product_type():
    assert cop._product_type("garbage") is None


def test_footprint_is_extracted_from_the_odata_wrapper():
    raw = "geography'SRID=4326;POLYGON ((93.1 23.4, 93.4 24.9, 91.0 25.3, 93.1 23.4))'"
    wkt = cop._footprint_wkt(raw)
    assert wkt.startswith("POLYGON")
    assert wkt.endswith("))")
    assert "SRID" not in wkt


def test_an_unexpected_footprint_format_yields_none_not_a_guess():
    """A wrong footprint is worse than no footprint -- it would claim radar
    covered ground it never saw."""
    assert cop._footprint_wkt(None) is None
    assert cop._footprint_wkt("") is None
    assert cop._footprint_wkt("geography'SRID=4326;POINT(92 24)'") is None


def test_timestamps_are_parsed_as_utc():
    parsed = cop._parse_datetime("2026-09-08T23:46:57.000Z")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.hour == 23


def test_the_corridor_point_is_inside_the_corridor():
    lon, lat = cop.CORRIDOR_POINT
    assert 91.9 < lon < 93.4
    assert 24.5 < lat < 25.7


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT elevation_m FROM roads LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no corridor database with terrain (expected in CI)"
)


@needs_db
def test_almost_every_road_has_an_elevation():
    from sqlalchemy import func, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        total = db.execute(select(func.count(Road.id))).scalar_one()
        sampled = db.execute(
            select(func.count(Road.elevation_m))
        ).scalar_one()
    assert sampled / total > 0.99, "DEM coverage should be near-total for this corridor"


@needs_db
def test_elevations_are_physically_plausible_for_this_corridor():
    """Barak valley floor sits around 20 m; the Dima Hasao hills pass 1000 m.
    Anything outside this range means the raster was sampled wrong -- a
    misread transform typically lands values in the thousands or below sea
    level, both obviously wrong here and both silent."""
    from sqlalchemy import func, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        lo, hi = db.execute(
            select(func.min(Road.elevation_m), func.max(Road.elevation_m))
        ).one()
    assert lo > 0, "no corridor road is below sea level"
    assert lo < 50, "the valley floor should appear in the data"
    assert 500 < hi < 3000, "the hills should appear, but this is not the Himalaya"


@needs_db
def test_the_hill_district_is_measurably_higher_than_the_valley():
    """The whole reason terrain was added: Dima Hasao and Cachar are treated
    identically by a district-level flood score, and they are nothing alike."""
    from sqlalchemy import func, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        means = dict(
            db.execute(
                select(Road.district, func.avg(Road.elevation_m))
                .where(Road.district.isnot(None))
                .group_by(Road.district)
            ).all()
        )
    assert means["Dima Hasao"] > 300
    assert means["Cachar"] < 100
    assert means["Dima Hasao"] > means["Cachar"] * 5


@needs_db
def test_slope_is_never_negative_and_never_absurd():
    from sqlalchemy import func, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        lo, hi = db.execute(
            select(func.min(Road.slope_pct), func.max(Road.slope_pct))
        ).one()
    assert lo >= 0, "slope is an absolute gradient"
    assert hi < 100, "a road steeper than 45 degrees is a data error, not a road"


@needs_db
def test_elevation_records_its_source():
    from sqlalchemy import select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        source = db.execute(
            select(Road.elevation_source).where(Road.elevation_m.isnot(None)).limit(1)
        ).scalar_one()
    assert source == "copernicus_dem_glo30"


@needs_db
def test_satellite_coverage_reports_recency_and_says_what_it_is_not():
    r = client.get("/api/v1/hazards/satellite-coverage")
    assert r.status_code == 200
    body = r.json()
    if body["passes_recorded"] == 0:
        pytest.skip("no coverage recorded yet")
    assert body["hours_since_last_pass"] is not None
    assert body["observed_revisit_days"]
    assert "not flood maps" in body["caveats"]["coverage_not_flood_extent"]
    assert "cadence_is_observed" in body["caveats"]


@needs_db
def test_recorded_passes_are_grd_only():
    """SLC and RAW products for the same pass must not inflate the count."""
    body = client.get("/api/v1/hazards/satellite-coverage").json()
    if body["passes_recorded"] == 0:
        pytest.skip("no coverage recorded yet")
    for p in body["recent_passes"]:
        assert p["product_type"] in cop.USEFUL_PRODUCT_TYPES


@needs_db
def test_distinct_passes_are_fewer_than_products():
    """Several products share one acquisition; 'how often does radar look'
    counts passes, not files."""
    body = client.get("/api/v1/hazards/satellite-coverage").json()
    if body["passes_recorded"] == 0:
        pytest.skip("no coverage recorded yet")
    assert body["passes_recorded"] <= body["products_recorded"]
