"""
Daily rainfall per district, from NASA's GPM IMERG satellite product.

WHY THIS SOURCE
Rainfall is the model's biggest missing input: without it a flood is only
visible once a district has already been listed as affected. Every free
source was re-checked against its robots.txt (docs/decisions/0014); the
open ones are Copernicus ERA5, which runs about five days behind and so
cannot inform tomorrow's forecast, and this one.

WHICH IMERG
`GPM_3IMERGDL` -- the *Late* daily run. Three products exist:

    Early   ~4 hours behind, least corrected
    Late    ~1 day behind, gauge-adjusted            <- this one
    Final   ~3 months behind, fully calibrated

Late is the only one that is both good enough to train on and current enough
to use. The daily job targets *yesterday's* report, and yesterday's Late file
is published by then. Final would be better for the historical half, but
training on Final and forecasting on Late would mean the model learns from
numbers it will never see live -- a quiet way to look better in testing than
in use.

HOW MUCH IS DOWNLOADED
OPeNDAP subsetting, so each request returns only the grid cells over one
district on one day -- a few hundred bytes -- instead of a 25 MB global grid.
One request per district-day is still far too many, so a day is fetched as
one request covering all of Assam, and districts are averaged out of that
single grid.

CREDENTIALS
A free NASA Earthdata account, in EARTHDATA_USERNAME / EARTHDATA_PASSWORD,
which live in the operator's environment and never in the repo. The GES DISC
archive also has to be authorised once in the account's profile; without that
the server answers 401 no matter how correct the password is, so that case is
reported as its own error rather than "login failed".
"""

from __future__ import annotations

import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from app.services.ingestion.http_client import FetchError, PoliteClient
from app.services.weather.points import DistrictPoint

HOST = "https://gpm1.gesdisc.eosdis.nasa.gov"
DATA_DIR = HOST + "/data/GPM_L3/GPM_3IMERGDL.07/{year}/{month:02d}/"
OPENDAP_DIR = HOST + "/opendap/GPM_L3/GPM_3IMERGDL.07/{year}/{month:02d}/"
URS_HOST = "urs.earthdata.nasa.gov"

# The IMERG grid: 0.1 degrees, cell centres at -179.95, -179.85, ... and
# -89.95, -89.85, ... The arrays are indexed [time][lon][lat].
GRID_STEP = 0.1
LON_ORIGIN = -180.0
LAT_ORIGIN = -90.0

# IMERG marks missing cells with -9999.9. Anything below this is not rain.
MISSING_BELOW = -100.0

VARIABLE = "precipitation"

# One request per day covers this box rather than one per district.
ASSAM_BOX = (89.5, 96.2, 23.8, 28.3)  # west, east, south, north


class EarthdataAuthError(FetchError):
    """Credentials missing, wrong, or the archive not authorised."""


@dataclass(frozen=True)
class Grid:
    """A rectangle of the IMERG grid, with the index each axis starts at."""

    values: list[list[float]]  # [lon][lat]
    lon_start: int
    lat_start: int

    def cell(self, lon_index: int, lat_index: int) -> float | None:
        i, j = lon_index - self.lon_start, lat_index - self.lat_start
        if not (0 <= i < len(self.values) and 0 <= j < len(self.values[i])):
            return None
        v = self.values[i][j]
        return None if v < MISSING_BELOW else v


def grid_index(value: float, origin: float) -> int:
    """Which grid cell a coordinate falls in."""
    return int((value - origin) / GRID_STEP)


def credentials() -> tuple[str, str]:
    user = os.environ.get("EARTHDATA_USERNAME", "").strip()
    password = os.environ.get("EARTHDATA_PASSWORD", "")
    if not user or not password:
        raise EarthdataAuthError(
            "EARTHDATA_USERNAME / EARTHDATA_PASSWORD are not set. Register free "
            "at https://urs.earthdata.nasa.gov/users/new, authorise 'NASA GESDISC "
            "DATA ARCHIVE' in your profile, then set both in your environment."
        )
    return user, password


def earthdata_opener(user: str, password: str) -> urllib.request.OpenerDirector:
    """An opener that can complete the Earthdata login dance.

    A data request redirects to urs.earthdata.nasa.gov, which asks for Basic
    auth, sets a session cookie and redirects back. Both handlers are needed:
    without the cookie the redirect loops, and the password is only ever
    offered to the URS host.
    """
    passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    passwords.add_password(None, URS_HOST, user, password)
    return urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(passwords),
        urllib.request.HTTPCookieProcessor(),
    )


_FILENAME = re.compile(r"3B-DAY-L\.MS\.MRG\.3IMERG\.(\d{8})-S000000-E235959\.V07[A-Z]\.nc4")


def filenames_in_listing(html: str) -> dict[str, str]:
    """Map YYYYMMDD -> filename from a month's directory listing.

    The version suffix moves (V07B became V07C partway through the record),
    so the name is read from the archive rather than constructed.
    """
    return {m.group(1): m.group(0) for m in _FILENAME.finditer(html)}


@dataclass(frozen=True)
class AsciiGrid:
    rows: list[list[float]]  # [lon][lat]
    lons: list[float]        # the longitude each row is labelled with
    lats: list[float]        # the latitude of each column


_ROW_LON = re.compile(r"\.lon=(-?[\d.]+)\]")


def parse_ascii(body: str, variable: str = VARIABLE) -> AsciiGrid:
    """Pull the values and their coordinates out of a GES DISC ascii response.

    The archive (a Hyrax server) labels every row with its coordinates:

        Dataset: 3B-DAY-L....nc4
        precipitation.lat, 23.85, 23.95, ...
        precipitation.precipitation[precipitation.time=16583][precipitation.lon=100.05], 0.76, ...

    The labels are kept rather than thrown away, so the caller can check the
    cells it asked for are the cells it got. A grid read one cell out of step
    gives rainfall that is plausible everywhere and right nowhere.
    """
    rows: list[list[float]] = []
    lons: list[float] = []
    lats: list[float] = []
    for line in body.splitlines():
        label, sep, values = line.strip().partition(",")
        if not sep:
            continue
        numbers = [float(v) for v in values.split(",") if v.strip()]
        if label == f"{variable}.lat":
            lats = numbers
        elif label.startswith(f"{variable}.{variable}["):
            lon = _ROW_LON.search(label)
            if lon is None:
                raise FetchError(f"Row without a longitude label: {label!r}")
            lons.append(float(lon.group(1)))
            rows.append(numbers)
    if not rows:
        raise FetchError(
            f"No {variable} rows in the OPeNDAP response; first 200 characters: "
            f"{body[:200]!r}"
        )
    return AsciiGrid(rows=rows, lons=lons, lats=lats)


def cell_centre(index: int, origin: float) -> float:
    return origin + (index + 0.5) * GRID_STEP


def check_alignment(parsed: AsciiGrid, lon_start: int, lat_start: int) -> None:
    """Refuse a grid whose coordinates are not the cells requested."""
    expected_lon = cell_centre(lon_start, LON_ORIGIN)
    expected_lat = cell_centre(lat_start, LAT_ORIGIN)
    if not parsed.lons or not parsed.lats:
        raise FetchError("OPeNDAP response carried no coordinates to check against")
    if abs(parsed.lons[0] - expected_lon) > 0.01 or abs(parsed.lats[0] - expected_lat) > 0.01:
        raise FetchError(
            f"Grid misaligned: asked for the cell at ({expected_lon:.2f}, {expected_lat:.2f}), "
            f"got ({parsed.lons[0]:.2f}, {parsed.lats[0]:.2f})"
        )
    if any(len(r) != len(parsed.lats) for r in parsed.rows):
        raise FetchError("OPeNDAP rows are not all as long as the latitude axis")


class ImergClient:
    """Reads one day of rainfall at a time. One instance per run."""

    def __init__(self, client: PoliteClient | None = None) -> None:
        user, password = credentials()
        self._client = client or PoliteClient(
            timeout=120.0,
            crawl_delay=1.0,
            opener=earthdata_opener(user, password),
        )

    def _fetch(self, url: str) -> str:
        try:
            return self._client.fetch(url).text
        except FetchError as exc:
            if "401" in str(exc) or "403" in str(exc):
                raise EarthdataAuthError(
                    f"{url} returned unauthorised. Either the Earthdata credentials "
                    "are wrong, or 'NASA GESDISC DATA ARCHIVE' has not been authorised "
                    "in the account's profile at https://urs.earthdata.nasa.gov/profile."
                ) from exc
            raise

    @lru_cache(maxsize=32)  # noqa: B019 -- per-instance cache, instance is per-run
    def _listing(self, year: int, month: int) -> dict[str, str]:
        return filenames_in_listing(self._fetch(DATA_DIR.format(year=year, month=month)))

    def filename_for(self, day: date) -> str | None:
        """None when the day is not published yet -- normal for the last day
        or two, since the Late run lags reality."""
        return self._listing(day.year, day.month).get(day.strftime("%Y%m%d"))

    def grid_for(self, day: date, box: tuple[float, float, float, float] = ASSAM_BOX) -> Grid | None:
        name = self.filename_for(day)
        if name is None:
            return None
        west, east, south, north = box
        lon0, lon1 = grid_index(west, LON_ORIGIN), grid_index(east, LON_ORIGIN)
        lat0, lat1 = grid_index(south, LAT_ORIGIN), grid_index(north, LAT_ORIGIN)
        url = (
            OPENDAP_DIR.format(year=day.year, month=day.month)
            + f"{name}.ascii?{VARIABLE}[0][{lon0}:{lon1}][{lat0}:{lat1}]"
        )
        parsed = parse_ascii(self._fetch(url))
        check_alignment(parsed, lon0, lat0)
        return Grid(values=parsed.rows, lon_start=lon0, lat_start=lat0)


def district_rainfall(grid: Grid, point: DistrictPoint) -> float | None:
    """Mean rainfall over the cells in a district's box, in mm.

    None when every cell is missing, which is different from zero: a day the
    satellite could not see must not be taught to the model as a dry day.
    """
    lon0 = grid_index(point.lon - point.half_lon, LON_ORIGIN)
    lon1 = grid_index(point.lon + point.half_lon, LON_ORIGIN)
    lat0 = grid_index(point.lat - point.half_lat, LAT_ORIGIN)
    lat1 = grid_index(point.lat + point.half_lat, LAT_ORIGIN)

    values = [
        v
        for i in range(lon0, lon1 + 1)
        for j in range(lat0, lat1 + 1)
        if (v := grid.cell(i, j)) is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)
