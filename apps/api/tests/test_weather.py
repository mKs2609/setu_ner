"""
Tests for the rainfall input: grid arithmetic, parsing, and district lookup.

Everything here is pure. The one thing these cannot check is whether the
archive's numbers mean what we think they mean -- that is what
`python -m app.services.weather.check` does, against the live server.
"""

from __future__ import annotations

import pytest

from app.services.model.dataset import district_key
from app.services.weather.imerg import (
    LAT_ORIGIN,
    LON_ORIGIN,
    Grid,
    check_alignment,
    district_rainfall,
    filenames_in_listing,
    grid_index,
    parse_ascii,
)
from app.services.weather.points import DistrictPoint, coverage, load_points

# A real response from the archive (2025-06-01, cells [2800:2802][1138:1141]),
# with one value replaced by the fill value to exercise the missing case.
SAMPLE_ASCII = """Dataset: 3B-DAY-L.MS.MRG.3IMERG.20250601-S000000-E235959.V07B.nc4
precipitation.lat, 23.85, 23.95, 24.05, 24.15
precipitation.precipitation[precipitation.time=16583][precipitation.lon=100.05], 0.76, 1.51, 1.505, 1.91
precipitation.precipitation[precipitation.time=16583][precipitation.lon=100.15], 0.535, -9999.9, 1.245, 1.28
precipitation.precipitation[precipitation.time=16583][precipitation.lon=100.25], 0.735, 0.84, 1.165, 1.245
"""


def test_grid_index_puts_a_coordinate_in_the_right_cell():
    # Cell centres sit at -179.95, -179.85, ...: the cell starting at 92.0
    # holds everything from 92.0 up to but not including 92.1.
    assert grid_index(92.05, LON_ORIGIN) == grid_index(92.0, LON_ORIGIN)
    assert grid_index(92.15, LON_ORIGIN) == grid_index(92.05, LON_ORIGIN) + 1
    assert grid_index(24.05, LAT_ORIGIN) == 1140
    assert grid_index(0.0, LAT_ORIGIN) == 900


def test_parse_ascii_reads_values_with_their_coordinates():
    parsed = parse_ascii(SAMPLE_ASCII)
    assert parsed.rows[0] == [0.76, 1.51, 1.505, 1.91]
    assert len(parsed.rows) == 3
    assert parsed.lons == [100.05, 100.15, 100.25]
    assert parsed.lats == [23.85, 23.95, 24.05, 24.15]


def test_the_cells_received_must_be_the_cells_requested():
    parsed = parse_ascii(SAMPLE_ASCII)
    check_alignment(parsed, lon_start=2800, lat_start=1138)  # what was asked for
    with pytest.raises(Exception) as exc:
        check_alignment(parsed, lon_start=2801, lat_start=1138)  # one cell out
    assert "misaligned" in str(exc.value)


def test_parse_ascii_refuses_a_response_with_no_data():
    with pytest.raises(Exception) as exc:
        parse_ascii("Error { code = 500; message = \"service unavailable\"; };")
    assert "OPeNDAP" in str(exc.value)


def test_grid_reports_missing_cells_as_missing_not_zero():
    grid = Grid(values=parse_ascii(SAMPLE_ASCII).rows, lon_start=100, lat_start=50)
    assert grid.cell(100, 50) == 0.76
    assert grid.cell(101, 51) is None  # the -9999.9 fill value
    assert grid.cell(999, 999) is None  # outside the fetched rectangle


def test_district_rainfall_averages_the_cells_in_the_box():
    grid = Grid(values=[[1.0, 3.0], [5.0, 7.0]], lon_start=0, lat_start=0)
    # A box small enough to land in one cell, placed on the first cell.
    point = DistrictPoint(
        key="x",
        name="X",
        lon=LON_ORIGIN + 0.05,
        lat=LAT_ORIGIN + 0.05,
        half_lon=0.04,
        half_lat=0.04,
    )
    assert district_rainfall(grid, point) == 1.0

    wider = DistrictPoint(
        key="x", name="X",
        lon=LON_ORIGIN + 0.1, lat=LAT_ORIGIN + 0.1, half_lon=0.1, half_lat=0.1,
    )
    assert district_rainfall(grid, wider) == pytest.approx((1.0 + 3.0 + 5.0 + 7.0) / 4)


def test_district_rainfall_is_none_when_every_cell_is_missing():
    grid = Grid(values=[[-9999.9]], lon_start=0, lat_start=0)
    point = DistrictPoint(
        key="x", name="X",
        lon=LON_ORIGIN + 0.05, lat=LAT_ORIGIN + 0.05, half_lon=0.01, half_lat=0.01,
    )
    assert district_rainfall(grid, point) is None


def test_filenames_are_read_from_the_listing_because_the_version_moves():
    html = (
        '<a href="3B-DAY-L.MS.MRG.3IMERG.20250601-S000000-E235959.V07B.nc4">a</a>'
        '<a href="3B-DAY-L.MS.MRG.3IMERG.20260919-S000000-E235959.V07C.nc4">b</a>'
        '<a href="3B-DAY-L.MS.MRG.3IMERG.20260919-S000000-E235959.V07C.nc4.xml">c</a>'
    )
    found = filenames_in_listing(html)
    assert found["20250601"].endswith("V07B.nc4")
    assert found["20260919"].endswith("V07C.nc4")


def test_every_district_the_report_names_has_a_rainfall_point():
    """The join that makes rainfall usable at all.

    The districts here are the ones the DRIMS reports actually name, spelled
    as the model keys them. A miss means that district would silently train
    with no rainfall, so it is a test rather than a log line.
    """
    report_districts = [
        "Cachar", "Dima Hasao", "Hailakandi", "Karimganj",
        "bajali", "baksa", "barpeta", "biswanath", "bongaigaon", "charaideo",
        "chirang", "darrang", "dhemaji", "dibrugarh", "goalpara", "golaghat",
        "hojai", "jorhat", "kamrup", "kamrupm", "karbianglong",
        "karbianglongwest", "kokrajhar", "lakhimpur", "majuli", "morigaon",
        "nagaon", "nalbari", "sivasagar", "sonitpur", "southsalmara",
        "tamulpur", "tinsukia", "udalguri",
    ]
    matched, unmatched = coverage(report_districts)
    assert unmatched == []
    assert len(matched) == len(report_districts)


def test_points_are_inside_assam():
    for point in load_points().values():
        assert 24.0 <= point.lat <= 28.2, point
        assert 89.5 <= point.lon <= 96.2, point
        assert 0.1 <= point.half_lat <= 1.0, point
        assert 0.1 <= point.half_lon <= 1.0, point


def test_a_name_that_lost_a_letter_to_the_page_margin_is_repaired():
    # 2025-10-06 prints "D hemaji"; the D never reached the text layer.
    assert district_key("hemaji") == district_key("Dhemaji") == "dhemaji"
    # Real districts with similar names stay separate.
    assert district_key("Kamrup") != district_key("Kamrup (M)")
