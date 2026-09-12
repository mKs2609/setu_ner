"""
Sentinel-1 coverage over the corridor, from the Copernicus Data Space
catalogue.

WHAT THIS DOES AND DELIBERATELY DOES NOT DO
It records **when radar looked at the corridor**. It does not produce flood
extent, and the reason is worth stating plainly rather than leaving as an
absence somebody discovers later.

  Search is open.      The OData catalogue answers queries anonymously, which
                       is how this module works at all.

  Download is not.     Asking for a scene returns 401 without a registered
                       Copernicus account.

  Processing is real   A 1.7 GB IW GRD scene becomes flood polygons only
  work.                after calibration, speckle filtering, terrain
                       correction and water thresholding. `0001` section 1
                       already found the bottleneck there is SAR expertise
                       rather than access, and said to keep it optional
                       rather than let it block the vertical slice.

Thresholding an unprocessed scene would produce flood boundaries fast and
they would be indefensible. So this records the honest half: coverage and
its recency.

WHY COVERAGE IS USEFUL ON ITS OWN
"Could anything independent have confirmed this report?" is a real question
with a real answer -- and if the last radar pass was nine days ago, that
answer is no, regardless of how good a flood-extent pipeline might be. The
observed cadence also says when the next opportunity arrives, computed from
the passes we actually saw rather than from orbit prediction we cannot do.

    https://catalogue.dataspace.copernicus.eu/odata/v1/Products
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.ingestion.http_client import FetchError, PoliteClient

SOURCE_NAME = "copernicus_dataspace_catalogue"
CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"

# A point in the middle of the corridor. A scene covering Silchar covers the
# valley, and Sentinel-1 IW swaths are 250 km wide -- far wider than the
# corridor -- so a point test is enough and a polygon test would only make
# the query fragile.
CORRIDOR_POINT = (92.78, 24.83)

# GRD is the product a flood pipeline would actually use. SLC and RAW are
# listed by the catalogue for the same pass and are not useful here, so they
# are filtered out rather than stored as noise.
USEFUL_PRODUCT_TYPES = ("IW_GRDH_1S", "IW_GRDM_1S")


@dataclass
class Acquisition:
    product_id: str
    name: str
    mission: str
    product_type: str | None
    acquired_at: datetime
    size_bytes: int | None
    online: bool | None
    footprint_wkt: str | None


def _parse_datetime(value: str) -> datetime:
    # The catalogue returns e.g. 2026-09-08T23:46:57.000Z
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _product_type(name: str) -> str | None:
    """Read the product type out of the scene name.

    The OData `Attributes` expansion carries it properly but costs an extra
    round trip per product. The naming convention has been stable for the
    life of the mission, so parsing the name is the cheaper honest option --
    and returning None when it does not match is better than guessing.
    """
    parts = name.split("_")
    if len(parts) < 4:
        return None
    for candidate in USEFUL_PRODUCT_TYPES:
        if candidate.replace("_", "") in name.replace("_", ""):
            return candidate
    return "_".join(parts[1:4]).rstrip("_") or None


def search(
    client: PoliteClient,
    *,
    since: datetime | None = None,
    limit: int = 50,
) -> list[Acquisition]:
    """Sentinel-1 scenes covering the corridor, newest first."""
    since = since or datetime.now(timezone.utc) - timedelta(days=30)
    lon, lat = CORRIDOR_POINT

    query = (
        f"$filter=Collection/Name eq 'SENTINEL-1'"
        f" and OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})')"
        f" and ContentDate/Start gt {since.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
        f"&$orderby=ContentDate/Start desc"
        f"&$top={int(limit)}"
    )
    url = f"{CATALOGUE}?{query}".replace(" ", "%20").replace("'", "%27")

    response = client.fetch(url)
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"Catalogue returned non-JSON: {response.text[:200]}") from exc

    out: list[Acquisition] = []
    for item in payload.get("value", []):
        name = item.get("Name", "")
        product_type = _product_type(name)
        if product_type not in USEFUL_PRODUCT_TYPES:
            continue
        out.append(
            Acquisition(
                product_id=item["Id"],
                name=name,
                mission="SENTINEL-1",
                product_type=product_type,
                acquired_at=_parse_datetime(item["ContentDate"]["Start"]),
                size_bytes=int(item["ContentLength"]) if item.get("ContentLength") else None,
                online=item.get("Online"),
                footprint_wkt=_footprint_wkt(item.get("Footprint")),
            )
        )
    return out


def _footprint_wkt(footprint: str | None) -> str | None:
    """The catalogue returns `geography'SRID=4326;POLYGON((...))'`.

    Returns None rather than a half-parsed shape when the format is not what
    we expect -- a wrong footprint is worse than no footprint, because it
    would claim radar covered ground it never saw.
    """
    if not footprint or "POLYGON" not in footprint:
        return None
    start = footprint.find("POLYGON")
    wkt = footprint[start:].rstrip("'").strip()
    return wkt or None
