"""
DRIMS Assam -- the Disaster Reporting and Information Management System run
by ASDMA, published at sdrf.assam.gov.in/dfr.

WHY THIS SOURCE, AND WHY IT REPLACED THE CWC PLAN
`0002` planned to ingest CWC's Daily Flood Situation Report by its dated URL
pattern. That pattern is dead: every date across a week of checks returns
404, and the listing page at cwc.gov.in/en/fmo/dfsra renders its publication
table with no rows at all. The script written against that pattern could not
have succeeded on any run.

DRIMS is a better source in every respect that matters here:

  live        A report per day, generated from what districts actually
              submitted, rather than an annual retrospective.
  structured  Real per-district tables, not prose.
  broad       One endpoint serves nine hazard types (flood, landslide,
              rainfall, earthquake, erosion, fire, lightning, storm,
              urban-flood) plus weather and CAP alerts, which is what makes
              the pluggable hazard architecture in `0001` section 3
              reachable rather than hypothetical.

              Being offered is not the same as being readable, though.
              Flood and landslide share one report template and this parser
              handles both. Rainfall does NOT -- it returns an IMD
              state-wise cumulated bulletin with an entirely different
              structure. `TEMPLATE_MARKERS` below detects which document we
              actually got, so an unreadable one fails the run instead of
              recording a success with zero rows.
  relevant    It reports **road, bridge and embankment damage per district**,
              with road name, location and coordinates when the district
              supplies them. That is the closest thing to ground truth this
              project has ever had for what it actually models.
  permitted   sdrf.assam.gov.in/robots.txt publishes an explicit empty
              Disallow, i.e. allow-all. We throttle anyway.

It also quotes CWC's river danger-level line ("as per CWC bulletin issued at
8 AM"), so the river signal the original CWC plan wanted arrives here anyway,
despite CWC's own bulletin URL being dead.

HOW THE DOWNLOAD WORKS
It is a Laravel form, not a plain file URL:

  1. GET  /dfr/download?type=<hazard>  -- returns a form page carrying a CSRF
     token in a hidden `_token` input, plus a session cookie.
  2. POST /dfr/download with `_token`, `type` and `date` (YYYY-MM-DD).
     Returns application/pdf for a date that has a report, and re-renders the
     HTML form for one that does not.

Both steps go through the polite client, so the token fetch is throttled and
robots-checked like everything else.

WHAT WE EXTRACT, AND WHAT WE DELIBERATELY DO NOT
The report has roughly two dozen sections. We parse the nine whose columns
are unambiguous and leave the rest alone -- relief camp demographics,
livestock, relief distributed, wildlife. Half-parsing a column whose meaning
we are guessing at would put authoritative-looking numbers in the database
that nobody could defend, which is the exact failure this project has
committed to avoiding. Unparsed rows are not lost: every observation keeps
its source row in `raw`, so widening the parser later needs no re-fetch.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.services.ingestion.districts import normalise_district
from app.services.ingestion.http_client import FetchError, PoliteClient

SOURCE_NAME = "drims_assam_daily_report"
BASE = "https://sdrf.assam.gov.in/dfr"

# The hazard types the endpoint accepts. Flood is what the corridor model
# needs today; the rest are listed because they are the extensibility story,
# and because "what else could this ingest?" deserves a concrete answer.
HAZARD_TYPES = {
    "flood": "flood",
    "landslide": "landslide",
    "rainfall": "rainfall",
    "earthquake": "earthquake",
    "erosion": "erosion",
    "fire": "fire",
    "lightning": "lightning",
    "storm": "storm",
    "urban-flood": "urban_flood",
}


@dataclass
class Observation:
    """One fact, before it is given provenance and stored."""

    metric: str
    value_num: float | None
    value_text: str | None
    unit: str | None
    place_name: str | None
    district: str | None
    raw: dict
    lon: float | None = None
    lat: float | None = None


@dataclass
class ReportFetch:
    pdf_bytes: bytes
    report_date: date
    source_url: str
    fetched_at: datetime


def fetch_report(client: PoliteClient, hazard: str, report_date: date) -> ReportFetch:
    """Pull one day's report. Raises FetchError when there is not one."""
    if hazard not in HAZARD_TYPES:
        raise ValueError(
            f"Unknown hazard {hazard!r}. Known: {', '.join(sorted(HAZARD_TYPES))}"
        )

    form_url = f"{BASE}/download?type={hazard}"
    form = client.fetch(form_url)
    match = re.search(r'name="_token"\s+value="([^"]+)"', form.text)
    if not match:
        raise FetchError(
            f"No CSRF token on {form_url}. The download form has probably "
            f"changed shape -- open it in a browser and check."
        )

    body = f"_token={match.group(1)}&type={hazard}&date={report_date.isoformat()}"
    resp = client.fetch(
        f"{BASE}/download",
        data=body.encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": form_url,
        },
    )

    if not resp.is_pdf:
        # The form re-renders as HTML when a date has no report. That is a
        # normal outcome, not a pipeline failure.
        raise FetchError(
            f"No {hazard} report published for {report_date.isoformat()} "
            f"(server returned {resp.content_type}, not a PDF)."
        )

    return ReportFetch(
        pdf_bytes=resp.content,
        report_date=report_date,
        source_url=form_url,
        fetched_at=datetime.now(timezone.utc),
    )


def _clean(cell: str | None) -> str:
    return " ".join((cell or "").split())


def _squash(label: str | None) -> str:
    """Lowercase with every space removed.

    The PDF breaks section labels mid-word across lines -- "Infrastructu re
    Damaged - Road" and "Embankme nt Breached" are real examples -- so
    matching on words is unreliable and matching on the squashed string is not.
    """
    return "".join((label or "").split()).lower()


def _as_number(text: str | None) -> float | None:
    cleaned = _clean(text).replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None
    return float(cleaned)


# Section label (squashed) -> the metrics readable from it, as
# {metric: (column index, unit)}.
#
# ONLY SECTIONS LISTED HERE ARE PARSED, and the section state is cleared by
# any label not in this map. That is what stops "Inmates In Relief Camps" and
# "Non Camp Inmates in Relief Distribution Centers" from being read as though
# they were "Relief Camps / Centres Opened" -- an earlier keyword-matching
# version made exactly that mistake and produced 52 bogus rows from 6 real ones.
SECTION_METRICS: dict[str, dict[str, tuple[int, str]]] = {
    "nameofrevenuecircleaffected": {"revenue_circles_affected": (2, "count")},
    "villagesaffected": {"villages_affected": (2, "count")},
    "reliefcamps/centresopened": {"relief_camps_opened": (2, "count")},
    "humanliveslost-confirmed": {"lives_lost_confirmed": (2, "people")},
    # The three that matter most to an accessibility model: live per-district
    # reports about the infrastructure this project routes over.
    "infrastructuredamaged-road": {"roads_damaged": (2, "count")},
    "infrastructuredamaged-bridge": {"bridges_damaged": (2, "count")},
    "infrastructuredamaged-embankmentbreached": {"embankments_breached": (2, "count")},
}

AFFECTED_LIST_SECTION = "districtaffected"

# The population section is NOT read by column index, although it is listed
# above with indices for its metrics' units. pdfplumber inserts empty cells
# that shift the columns on some rows, and reading index 5 then returned one
# of the component counts instead of the total -- 31 of 613 stored rows were
# wrong that way (Nagaon read as 2,534 people instead of 13,463). See
# `_population_and_crop`, which identifies the total arithmetically instead.
POPULATION_SECTION = "populationandcropareasubmerged"
# The 2025 template labels the same section "...Area Affected". Missing this
# alias meant the whole 2025 season stored no population figures at all.
POPULATION_SECTIONS = {POPULATION_SECTION, "populationandcropareaaffected"}

# People actually being supplied, which is what supply demand is built on
# (docs/decisions/0011). "Affected" is an upper bound on need; camp inmates
# and people drawing from relief distribution centres are the population a
# supply plan has to reach.
#
# Both templates print: Total, a revenue-circle breakdown, then Male, Female,
# Children (2025 adds Pregnant/Lactating and Persons with Disability). The
# total is the first number in the row and children the fourth; the
# breakdown cell is text and is skipped when numbers are collected.
INMATE_SECTIONS = {
    "inmatesinreliefcamps": "relief_camp_inmates",
    "noncampinmatesinreliefdistributioncenters": "relief_centre_inmates",
}

# "(Silchar | 4146)" -- a revenue circle and its count, as the inmate
# sections print them.
_CIRCLE_COUNT = re.compile(r"\(\s*([^|()]+?)\s*\|\s*([\d,]+)\s*\)")

# "(Sonai | Population Affected: 100 | Crop Area Submerged: 0)" -- the
# per-revenue-circle breakdown the report prints beside each district total.
_CIRCLE_POPULATION = re.compile(
    r"\(\s*([^|()]+?)\s*\|\s*Population\s*Affected:\s*([\d,]+)", re.IGNORECASE
)

# Sections that identify the standard DRIMS disaster-report template.
# Seeing any of them means we are looking at a document this parser
# understands, so zero rows means "nothing happened that day" rather
# than "we cannot read this". The flood and landslide reports both use
# this template; the rainfall type does not (it returns an IMD
# state-wise bulletin with a completely different structure).
TEMPLATE_MARKERS = {
    "districtaffected",
    "humanliveslost-confirmed",
    "infrastructuredamaged-road",
    "housesdamaged",
}

NOT_A_DISTRICT = {
    "", "district", "total", "grand total", "name of district",
    "name of affected districts", "no. of districts",
}

# Assam sits well inside this box. Used to sanity-check any coordinate pulled
# out of a damage row before trusting it.
ASSAM_BBOX = (89.0, 24.0, 96.5, 28.5)  # min lon, min lat, max lon, max lat


def _as_decimal_across_linebreak(text: str | None) -> float | None:
    """Parse a decimal that the PDF may have wrapped mid-number.

    Coordinate cells come through as "92.74235 7" -- the renderer broke the
    line inside the digits. Removing the spaces recovers 92.742357.

    Only values containing a decimal point are accepted, which is the whole
    safety of this: joining the digits of two unrelated whole numbers ("1 2"
    into 12) would be a silent corruption, but a coordinate always has a
    decimal point and two adjacent integers in one cell never do.
    """
    cleaned = _clean(text).replace(",", "")
    if "." not in cleaned:
        return None
    joined = cleaned.replace(" ", "")
    if not re.fullmatch(r"-?\d+\.\d+", joined):
        return None
    return float(joined)


def _scan_coordinates(row: list[str | None]) -> tuple[float, float] | None:
    """Find a plausible lon/lat pair anywhere in a damage row.

    The infrastructure tables do carry Longitude and Latitude columns, but
    pdfplumber's column detection shifts between pages of this document, so
    reading them by fixed index is unreliable. Scanning for values inside
    Assam's bounding box is robust to that drift and validates itself: a
    misread cell almost never lands inside the box. Anything failing the check
    yields no geometry at all rather than a confident wrong point.
    """
    min_lon, min_lat, max_lon, max_lat = ASSAM_BBOX
    lon = lat = None
    for cell in row:
        value = _as_decimal_across_linebreak(cell)
        if value is None:
            continue
        if lon is None and min_lon <= value <= max_lon:
            lon = value
        elif lat is None and min_lat <= value <= max_lat:
            lat = value
    if lon is None or lat is None:
        return None
    return lon, lat


def parse_report(
    pdf_bytes: bytes, hazard: str
) -> tuple[date | None, list[Observation], bool]:
    """Extract the district-level rows we can read with confidence.

    Returns (printed_date, observations, template_recognised).

    `printed_date` is the date printed inside the document. The caller checks
    it against the date it asked for: a form-driven download quietly serving a
    different day is a real risk, and comparing the two is the only way to
    catch it.

    `template_recognised` distinguishes the two very different reasons this
    can return nothing:

      recognised, empty   A real report on a day with no events. The flood and
                          landslide reports share one template, and on a quiet
                          day their district tables are simply empty. This is
                          a valid result.

      not recognised      The document is not the template at all. The
                          rainfall type, for instance, returns an IMD
                          state-wise cumulated bulletin with an entirely
                          different structure that this parser cannot read.

    Without the flag those two look identical -- zero rows and a successful
    run -- and the second would quietly look like "no hazards reported"
    forever. The caller is expected to fail the run on an unrecognised
    template rather than record a success.
    """
    import pdfplumber  # lazy: only ingestion needs it

    observations: list[Observation] = []
    printed_date: date | None = None
    recognised = False

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if printed_date is None:
                m = re.search(r"as on\s+(\d{2})-(\d{2})-(\d{4})", text)
                if m:
                    d, mo, y = (int(g) for g in m.groups())
                    printed_date = date(y, mo, d)
            for table in page.extract_tables():
                for row in table:
                    if row and _squash(row[0]) in TEMPLATE_MARKERS:
                        recognised = True
                observations.extend(_parse_table(table, hazard))

    return printed_date, _dedupe(observations), recognised


def _parse_table(table: list[list[str | None]], hazard: str) -> list[Observation]:
    """Walk one table, carrying the section label downward.

    The layout writes a section name in column 0 of its first row only and
    leaves it blank underneath, so the section has to be tracked as state
    rather than read per row.
    """
    out: list[Observation] = []
    section: str | None = None
    last_district: tuple[str, str | None] | None = None

    for row in table:
        if not row:
            continue

        label = _squash(row[0])
        if label:
            section = (
                label
                if label in SECTION_METRICS
                or label == AFFECTED_LIST_SECTION
                or label in POPULATION_SECTIONS
                or label in INMATE_SECTIONS
                else None
            )
            last_district = None

        if section is None or len(row) < 3:
            continue

        if section == AFFECTED_LIST_SECTION:
            out.extend(_parse_affected_list(row, hazard))
            continue

        name = _clean(row[1])
        if name.lower() in NOT_A_DISTRICT:
            # A continuation row. In the infrastructure sections these carry
            # the per-item detail -- road name, location, coordinates -- for
            # the district named in the row above, so the district is carried
            # downward. Only rows that yield a coordinate inside Assam become
            # observations; the rest are structural padding.
            if section.startswith("infrastructuredamaged") and last_district:
                point = _scan_coordinates(row)
                if point:
                    out.append(
                        _damage_point(row, section, hazard, last_district, point)
                    )
            continue

        last_district = (name, normalise_district(name))

        raw_row = [(_clean(c) or None) for c in row]
        district = normalise_district(name)
        coords = (
            _scan_coordinates(row)
            if section.startswith("infrastructuredamaged")
            else None
        )

        if section in POPULATION_SECTIONS:
            out.extend(_parse_population_row(row, name, district, hazard, raw_row))
            continue

        if section in INMATE_SECTIONS:
            out.extend(
                _parse_inmate_row(row, name, district, hazard, raw_row, section)
            )
            continue

        for metric, (col, unit) in SECTION_METRICS[section].items():
            if col >= len(row):
                continue
            value = _as_number(row[col])
            if value is None:
                continue
            out.append(
                Observation(
                    metric=metric,
                    value_num=value,
                    value_text=None,
                    unit=unit,
                    place_name=name,
                    district=district,
                    raw={"section": section, "row": raw_row, "hazard": hazard},
                    lon=coords[0] if coords else None,
                    lat=coords[1] if coords else None,
                )
            )
    return out


def _population_and_crop(row: list[str | None]) -> tuple[float | None, float | None]:
    """The district's total affected population and crop area, found by
    arithmetic rather than position.

    The section prints three population counts, their total, then crop area.
    The three counts always sum to the total, so the total is the first
    number that equals the sum of the three before it. That check is
    self-validating: a row whose numbers do not add up yields (None, None)
    and nothing is stored, rather than a confident wrong figure.
    """
    numbers = [n for n in (_as_number(c) for c in row[2:]) if n is not None]
    for i in range(len(numbers) - 3):
        a, b, c, total = numbers[i : i + 4]
        if abs((a + b + c) - total) < 0.5:
            crop = numbers[i + 4] if i + 4 < len(numbers) else None
            return total, crop
    return None, None


def _parse_population_row(
    row: list[str | None],
    name: str,
    district: str | None,
    hazard: str,
    raw_row: list[str | None],
) -> list[Observation]:
    out: list[Observation] = []
    raw = {"section": POPULATION_SECTION, "row": raw_row, "hazard": hazard}
    total, crop = _population_and_crop(row)
    if total is not None:
        out.append(Observation("population_affected", total, None, "people", name, district, raw))
    if crop is not None:
        out.append(Observation("crop_area_submerged", crop, None, "hectares", name, district, raw))

    # Per revenue circle. Each entry is self-labelled, so a breakdown the PDF
    # truncated still yields correct individual circles -- it just does not
    # sum to the district total, and consumers must not assume it does.
    text = " ".join(_clean(c) for c in row if c)
    for circle, value in _CIRCLE_POPULATION.findall(text):
        out.append(
            Observation(
                "population_affected_circle",
                float(value.replace(",", "")),
                None,
                "people",
                _clean(circle),
                district,
                {**raw, "district_as_printed": name},
            )
        )
    return out


def _parse_inmate_row(
    row: list[str | None],
    name: str,
    district: str | None,
    hazard: str,
    raw_row: list[str | None],
    section: str,
) -> list[Observation]:
    """Total people supplied, children among them, and the per-circle split.

    The component check is recorded rather than enforced: in the 2025
    template Male + Female + Children does not always equal Total (1 Jun 2025,
    Cachar: 2055 + 2299 + 710 = 5064 against 5066), because the extra
    vulnerability columns overlap. So the printed total is stored as printed,
    and `components_match` says whether it reconciles.
    """
    metric = INMATE_SECTIONS[section]
    numbers = [n for n in (_as_number(c) for c in row[2:]) if n is not None]
    if not numbers:
        return []
    total = numbers[0]
    components = numbers[1:4]
    raw = {
        "section": section,
        "row": raw_row,
        "hazard": hazard,
        "components_match": len(components) == 3 and abs(sum(components) - total) < 0.5,
    }
    out = [Observation(metric, total, None, "people", name, district, raw)]
    if len(components) == 3:
        out.append(
            Observation(f"{metric}_children", components[2], None, "people", name, district, raw)
        )

    text = " ".join(_clean(c) for c in row if c)
    for circle, value in _CIRCLE_COUNT.findall(text):
        out.append(
            Observation(
                f"{metric}_circle",
                float(value.replace(",", "")),
                None,
                "people",
                _clean(circle),
                district,
                {**raw, "district_as_printed": name},
            )
        )
    return out


def _damage_point(
    row: list[str | None],
    section: str,
    hazard: str,
    district: tuple[str, str | None],
    point: tuple[float, float],
) -> Observation:
    """One geolocated damaged-infrastructure item.

    This is the most directly useful thing the report publishes for this
    project: a real, dated, located report that a specific road or bridge is
    damaged. It is NOT yet matched to an edge in the road graph -- doing that
    honestly needs a distance threshold and a way to say "no confident match",
    which is its own piece of work. Storing the point now means that matching
    can be built later against real accumulated data instead of waiting on a
    flood to test it.
    """
    place, canonical = district
    described = [
        _clean(c)
        for c in row[3:]
        if c and _clean(c).lower() not in {"nil", "na", "-"} and _as_number(c) is None
    ]
    return Observation(
        metric="infrastructure_damage_point",
        value_num=None,
        value_text=" | ".join(described)[:500] or None,
        unit=None,
        place_name=place,
        district=canonical,
        raw={"section": section, "row": [(_clean(c) or None) for c in row],
             "hazard": hazard},
        lon=point[0],
        lat=point[1],
    )


def _parse_affected_list(row: list[str | None], hazard: str) -> list[Observation]:
    """The header row naming which districts are affected at all.

    Read from the table rather than the page prose: the prose puts the
    header's own words on the line between the label and the data, and a text
    regex happily mistakes those for a district name.
    """
    joined = next(
        (_clean(c) for c in row[2:] if c and "," in c and _as_number(c) is None),
        None,
    )
    if not joined:
        return []
    names = [n.strip() for n in joined.split(",") if n.strip()]
    return [
        Observation(
            metric="district_reported_affected",
            value_num=1.0,
            value_text=None,
            unit="boolean",
            place_name=name,
            district=normalise_district(name),
            raw={"affected_district_list": names, "hazard": hazard},
        )
        for name in names
    ]


def _dedupe(observations: list[Observation]) -> list[Observation]:
    """Drop exact repeats of the same fact.

    Sections continue across page breaks, so the same district row can be
    emitted twice. Repeats collapse only when the value matches too: two
    different values for one district and metric is a parsing bug we want to
    see, not something to hide behind a dedupe.
    """
    seen: set[tuple] = set()
    out: list[Observation] = []
    for obs in observations:
        key = (obs.metric, obs.place_name, obs.value_num)
        if key in seen:
            continue
        seen.add(key)
        out.append(obs)
    return out
