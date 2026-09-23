"""
Phase 2: terrain. Samples elevation and gradient for every road in the
corridor from the Copernicus DEM.

WHY TERRAIN MATTERS HERE
Two roads with identical district flood severity are not equally at risk if
one sits on a ridge and the other on the valley floor. The corridor spans
both extremes -- Silchar sits around 20 m, the Dima Hasao hills rise past
700 m -- and until now nothing in the data could tell them apart. The
baseline accessibility score treats every road in a district the same, which
is exactly the crudeness that terrain fixes.

Gradient does separate work. Flooding cares about how low a road is;
landslides care about how steep the ground is. The DRIMS source already
publishes landslide reports (see 0004), so the feature has somewhere to go.

THE SOURCE
Copernicus DEM GLO-30, 30 m, from the AWS Open Data bucket -- public, no
credentials, no rate limit published. The tiles are Cloud Optimized GeoTIFFs,
so rasterio reads the corridor window over HTTP rather than downloading 288 MB
of full tiles.

    https://copernicus-dem-30m.s3.amazonaws.com/

THE CAVEAT THAT MATTERS
**GLO-30 is a surface model, not a terrain model.** It records the top of
whatever is there -- tree canopy, buildings -- not bare ground. Over an open
road that is the road surface and the value is good. Under dense canopy, or
in a built-up street, the sampled elevation can sit several metres above the
actual carriageway.

That mostly does not matter for the comparison this feature exists to make
(valley floor versus hillside is a 700 m difference, not a 5 m one), but it
does matter for gradient on short narrow segments, where a canopy gap can
manufacture a slope that is not there. Both columns are therefore recorded
with their source, and `slope_pct` on short residential segments deserves
scepticism.

A hydrologically conditioned DEM such as MERIT would be better for flood
reasoning specifically. It is 90 m rather than 30 m, and swapping it in later
means changing one URL template here.

    RUN THIS LOCALLY, from geo/dem:
        pip install rasterio
        python sample_road_elevation.py            # all roads
        python sample_road_elevation.py --limit 500  # a quick check first
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict

try:
    import numpy as np
    import rasterio
    from rasterio.windows import Window, from_bounds
except ImportError:
    print("Missing dependencies. Run: pip install rasterio numpy")
    sys.exit(1)

import psycopg2

DEM_BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
SOURCE_LABEL = "copernicus_dem_glo30"

# The corridor, from the road graph's own extent with a small margin.
CORRIDOR = (91.9, 24.5, 93.4, 25.7)  # min lon, min lat, max lon, max lat

DEFAULT_DSN = "postgresql://setuner:setuner@localhost:5432/setuner"


def tile_url(lat: int, lon: int) -> str:
    name = f"Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM"
    return f"/vsicurl/{DEM_BUCKET}/{name}/{name}.tif"


def tiles_covering(bounds: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    min_lon, min_lat, max_lon, max_lat = bounds
    return [
        (lat, lon)
        for lat in range(math.floor(min_lat), math.ceil(max_lat))
        for lon in range(math.floor(min_lon), math.ceil(max_lon))
    ]


def fetch_roads(cur, limit: int | None) -> list[tuple]:
    """Endpoints and midpoint of every road, as plain coordinates.

    Three points rather than one: the midpoint gives the road's elevation,
    and the two ends give the gradient along it. Sampling the whole geometry
    would be more faithful and far more expensive for a feature whose job is
    to separate hillside from floodplain.
    """
    cur.execute(
        """
        SELECT id,
               length_km,
               ST_X(ST_StartPoint(geometry::geometry)) AS x1,
               ST_Y(ST_StartPoint(geometry::geometry)) AS y1,
               ST_X(ST_LineInterpolatePoint(geometry::geometry, 0.5)) AS xm,
               ST_Y(ST_LineInterpolatePoint(geometry::geometry, 0.5)) AS ym,
               ST_X(ST_EndPoint(geometry::geometry)) AS x2,
               ST_Y(ST_EndPoint(geometry::geometry)) AS y2
        FROM roads
        ORDER BY id
        """
        + (f" LIMIT {int(limit)}" if limit else "")
    )
    return cur.fetchall()


def sample_tile(lat: int, lon: int, points: list[tuple[int, int, float, float]]):
    """Sample one tile for the points that fall inside it.

    Reads the corridor's intersection with the tile as a single window, then
    indexes it with numpy. One HTTP range read for thousands of points beats
    one read per point by a very wide margin.
    """
    url = tile_url(lat, lon)
    results: dict[tuple[int, int], float] = {}

    with rasterio.open(url) as src:
        left = max(src.bounds.left, CORRIDOR[0])
        bottom = max(src.bounds.bottom, CORRIDOR[1])
        right = min(src.bounds.right, CORRIDOR[2])
        top = min(src.bounds.top, CORRIDOR[3])
        if left >= right or bottom >= top:
            return results

        window = from_bounds(left, bottom, right, top, src.transform)
        window = Window(
            int(window.col_off), int(window.row_off),
            int(math.ceil(window.width)), int(math.ceil(window.height)),
        )
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        nodata = src.nodata

        inv = ~transform
        for road_id, slot, x, y in points:
            col, row = inv * (x, y)
            col, row = int(col), int(row)
            if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
                continue
            value = float(data[row, col])
            # GLO-30 marks sea and voids with nodata; a road there is a bad
            # sample, not a road at sea level.
            if nodata is not None and value == nodata:
                continue
            if not np.isfinite(value):
                continue
            results[(road_id, slot)] = value

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample road elevation from Copernicus DEM.")
    parser.add_argument("--limit", type=int, default=None, help="Only this many roads.")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    cur = conn.cursor()

    roads = fetch_roads(cur, args.limit)
    print(f"roads to sample: {len(roads):,}")

    # Group every sample point by the tile it falls in, so each tile is opened
    # and read exactly once.
    by_tile: dict[tuple[int, int], list] = defaultdict(list)
    lengths: dict[int, float] = {}
    for road_id, length_km, x1, y1, xm, ym, x2, y2 in roads:
        lengths[road_id] = length_km or 0.0
        for slot, (x, y) in enumerate(((x1, y1), (xm, ym), (x2, y2))):
            by_tile[(math.floor(y), math.floor(x))].append((road_id, slot, x, y))

    samples: dict[tuple[int, int], float] = {}
    for (lat, lon), points in sorted(by_tile.items()):
        if (lat, lon) not in tiles_covering(CORRIDOR):
            print(f"  N{lat} E{lon}: outside the corridor, skipped ({len(points)} points)")
            continue
        print(f"  N{lat} E{lon}: {len(points):,} points ...", end="", flush=True)
        try:
            got = sample_tile(lat, lon, points)
            samples.update(got)
            print(f" {len(got):,} sampled")
        except Exception as exc:  # noqa: BLE001
            print(f" FAILED: {exc}")

    updates = []
    no_sample = 0
    for road_id in lengths:
        mid = samples.get((road_id, 1))
        start = samples.get((road_id, 0))
        end = samples.get((road_id, 2))

        elevation = mid if mid is not None else start if start is not None else end
        if elevation is None:
            no_sample += 1
            continue

        slope = None
        if start is not None and end is not None:
            metres = (lengths.get(road_id) or 0.0) * 1000.0
            # Below ~30 m the two endpoints can land in the same DEM pixel, so
            # the "gradient" would be noise divided by a tiny number.
            if metres >= 30:
                slope = round(abs(end - start) / metres * 100.0, 3)

        updates.append((round(elevation, 2), slope, SOURCE_LABEL, road_id))

    print(f"\nwriting {len(updates):,} roads ({no_sample:,} had no usable sample)")
    cur.executemany(
        "UPDATE roads SET elevation_m=%s, slope_pct=%s, elevation_source=%s WHERE id=%s",
        updates,
    )
    conn.commit()

    cur.execute(
        """
        SELECT count(elevation_m), round(min(elevation_m)::numeric,1),
               round(max(elevation_m)::numeric,1), round(avg(elevation_m)::numeric,1),
               count(slope_pct), round(max(slope_pct)::numeric,1)
        FROM roads
        """
    )
    n, lo, hi, avg, n_slope, max_slope = cur.fetchone()
    print(f"\nelevation set on {n:,} roads: {lo}-{hi} m (mean {avg})")
    print(f"slope set on {n_slope:,} roads, steepest {max_slope}%")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
