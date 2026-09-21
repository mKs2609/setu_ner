"""
A live check that the rainfall archive means what the code assumes.

    python -m app.services.weather.check

The unit tests cover the arithmetic; they cannot cover "is this variable in
millimetres per day, and is the array really [time][lon][lat]". Getting
either wrong produces numbers that look plausible and are wrong -- rain in
mm/hour is a 24x error, and swapped axes silently reads a district hundreds
of kilometres away. So this asks the server, prints what it says, and checks
the two claims it can check on its own:

  * a known heavy-rain day over the Barak Valley reads as heavy rain
  * the same day's driest district reads as much drier

Run it after changing anything about the fetch, and after NASA changes the
product version.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from app.services.weather.imerg import (
    OPENDAP_DIR,
    EarthdataAuthError,
    ImergClient,
    district_rainfall,
)
from app.services.weather.points import load_points

# 2025-06-01: the Barak Valley flood that opened the 2025 season. The report
# for the following days lists Cachar, Karimganj and Hailakandi as affected,
# so rainfall over them should be substantial rather than a trace.
WET_DAY = date(2025, 6, 1)


def main() -> int:
    try:
        client = ImergClient()
    except EarthdataAuthError as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"checking the {WET_DAY} file")
    name = client.filename_for(WET_DAY)
    if name is None:
        print(f"FAILED: no IMERG file published for {WET_DAY}")
        return 1
    print(f"  file: {name}")

    # What the archive says about the variable, in its own words.
    das = client._fetch(OPENDAP_DIR.format(year=WET_DAY.year, month=WET_DAY.month) + name + ".das")
    block = das.split("precipitation {", 1)[-1].split("}", 1)[0]
    print("  precipitation attributes, as published:")
    for line in block.strip().splitlines():
        line = line.strip()
        if any(k in line for k in ("units", "FillValue", "long_name")):
            print(f"    {line}")

    dds = client._fetch(OPENDAP_DIR.format(year=WET_DAY.year, month=WET_DAY.month) + name + ".dds")
    shape = [ln.strip() for ln in dds.splitlines() if "precipitation[" in ln]
    print(f"  declared shape: {shape[0] if shape else 'not found'}")

    grid = client.grid_for(WET_DAY)
    if grid is None:
        print("FAILED: no grid returned")
        return 1

    points = load_points()
    rain = {k: district_rainfall(grid, p) for k, p in points.items()}
    measured = {k: v for k, v in rain.items() if v is not None}
    if not measured:
        print("FAILED: every district came back missing")
        return 1

    ranked = sorted(measured.items(), key=lambda kv: -kv[1])
    print(f"  {len(measured)}/{len(points)} districts measured")
    print("  wettest:")
    for k, v in ranked[:5]:
        print(f"    {k:22s} {v:7.1f} mm")
    print("  driest:")
    for k, v in ranked[-3:]:
        print(f"    {k:22s} {v:7.1f} mm")

    problems = []
    corridor = [rain.get(k) for k in ("Cachar", "Karimganj", "Hailakandi")]
    corridor = [v for v in corridor if v is not None]
    if not corridor:
        problems.append("no rainfall for the corridor districts")
    elif max(corridor) < 20:
        problems.append(
            f"the corridor's wettest district reads {max(corridor):.1f} mm on a day "
            "that flooded it -- suspect units (mm/hour rather than mm/day) or axis order"
        )
    if ranked[0][1] > 2000:
        problems.append(f"{ranked[0][1]:.0f} mm in a day is not physical -- check the fill value")
    if ranked[0][1] - ranked[-1][1] < 1:
        problems.append("every district reads the same -- the box may be collapsing to one cell")

    # The most recent day available, which is what the daily job depends on.
    today = date.today()
    latest = next(
        (d for d in (today - timedelta(days=n) for n in range(1, 6)) if client.filename_for(d)),
        None,
    )
    print(f"  most recent published day: {latest} (today is {today})")
    if latest is None:
        problems.append("nothing published in the last five days")

    if problems:
        print("\nFAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: units, axis order and freshness all look right.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
