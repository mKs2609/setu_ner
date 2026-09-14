"""
How much has to reach whom: demand per revenue circle, from the DRIMS report.

WHO IS COUNTED
`0001` section 2.4 warned that the original demand formula --
population x severity x vulnerability x duration x coefficient -- had every
coefficient invented. This does not use it. It counts people the report says
are being supplied:

  relief camp inmates            people living in a relief camp
  relief centre (non-camp)       people drawing supplies from a relief
  inmates                        distribution centre without living there

Both are printed per district and per revenue circle, every day. "Population
affected" is reported alongside for context but is NOT planned for: it counts
everyone whose area flooded, most of whom never need supplying, and planning
for it would overstate need several-fold (1 Jun 2025, Cachar: 103,790
affected, 5,288 in camps or at centres).

HOW PEOPLE BECOME QUANTITIES
Per person, per day, from published norms -- see NORMS, where each carries its
source and whether it is cited or derived. The operator can override any of
them; the defaults exist so a plan starts from a defensible number rather than
a blank.

WHAT IS NOT CLAIMED
  - Where the camps are. Demand is placed at the revenue circle's
    headquarters town (gazetteer.py), which is where a supply run would be
    addressed, not the location of any camp.
  - Medical supplies. There is no defensible per-person-per-day quantity for
    them; emergency health kits such as WHO's IEHK are sized for thousands of
    people over months and belong in a restocking plan, not a daily run.
  - Completeness. The report's circle breakdown is sometimes truncated in the
    PDF. When circles do not add up to the district total, the difference is
    reported as unattributed rather than spread across circles by guesswork.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.db.models import HazardObservation, IngestRun
from app.services.ingestion.sources import drims
from app.services.logistics import gazetteer

CAMP = "relief_camp_inmates"
CENTRE = "relief_centre_inmates"
AFFECTED = "population_affected"


@dataclass(frozen=True)
class Norm:
    key: str
    label: str
    unit: str
    per_person_per_day: float
    kg_per_unit: float
    urgency: float
    source: str
    basis: str  # cited | derived | judgement


NORMS: dict[str, Norm] = {
    "water": Norm(
        key="water",
        label="Drinking and domestic water",
        unit="litres",
        per_person_per_day=15.0,
        kg_per_unit=1.0,
        urgency=3.0,
        source=(
            "Sphere Handbook (2018), water supply standard 2.1: a minimum of 15 litres "
            "per person per day for drinking, cooking and personal hygiene."
        ),
        basis="cited",
    ),
    "food": Norm(
        key="food",
        label="Dry food rations",
        unit="ration-days",
        per_person_per_day=1.0,
        kg_per_unit=0.6,
        urgency=2.0,
        source=(
            "Sphere Handbook (2018) planning figure of 2,100 kcal per person per day. "
            "0.6 kg per ration-day is derived, not cited: dry cereals and pulses carry "
            "about 3.5 kcal per gram, and 2,100 / 3.5 = 600 g."
        ),
        basis="derived",
    ),
}

URGENCY_NOTE = (
    "Urgency weights (water 3, food 2) are a stated judgement, not a measurement: "
    "people survive days without food and far less without water, so when supply "
    "cannot cover both, water shortfalls are penalised more."
)


@dataclass
class CircleDemand:
    district: str
    circle: str
    camp_inmates: float = 0.0
    centre_inmates: float = 0.0
    affected: float | None = None
    lon: float | None = None
    lat: float | None = None
    located_as: str | None = None
    location_note: str | None = None
    conflicts: list[str] = field(default_factory=list)

    @property
    def people(self) -> float:
        return self.camp_inmates + self.centre_inmates

    def quantities(self, norms: dict[str, Norm], horizon_days: int) -> dict[str, float]:
        return {
            k: round(self.people * n.per_person_per_day * horizon_days, 1)
            for k, n in norms.items()
        }


@dataclass
class DemandEstimate:
    as_of: date
    horizon_days: int
    circles: list[CircleDemand]
    unattributed: dict[str, dict[str, float]]
    norms: dict[str, Norm]

    @property
    def located(self) -> list[CircleDemand]:
        return [c for c in self.circles if c.lon is not None and c.people > 0]

    @property
    def unlocated(self) -> list[CircleDemand]:
        return [c for c in self.circles if c.lon is None and c.people > 0]


def published_days(db) -> list[date]:
    return sorted(
        d
        for (d,) in db.execute(
            select(IngestRun.target_date)
            .where(
                IngestRun.source == drims.SOURCE_NAME,
                IngestRun.hazard_type == "flood",
                IngestRun.status == "success",
                IngestRun.target_date.isnot(None),
            )
            .distinct()
        )
    )


def _rows(db, as_of: date | None, metrics: list[str]):
    stmt = select(
        HazardObservation.source_document_date,
        HazardObservation.district,
        HazardObservation.place_name,
        HazardObservation.metric,
        HazardObservation.value_num,
    ).where(
        HazardObservation.source == drims.SOURCE_NAME,
        HazardObservation.hazard_type == "flood",
        HazardObservation.metric.in_(metrics),
        HazardObservation.district.isnot(None),  # corridor districts only
    )
    if as_of is not None:
        stmt = stmt.where(HazardObservation.source_document_date == as_of)
    return db.execute(stmt).all()


def supply_days(db) -> list[dict]:
    """Report days on which anyone in the corridor was being supplied -- the
    days worth planning against, for the UI's date picker."""
    totals: dict[date, float] = defaultdict(float)
    for d, _district, _place, _metric, value in _rows(db, None, [CAMP, CENTRE]):
        totals[d] += value or 0.0
    return [
        {"date": d.isoformat(), "people": int(v)}
        for d, v in sorted(totals.items(), reverse=True)
        if v > 0
    ]


def estimate(db, as_of: date | None = None, horizon_days: int = 1,
             norms: dict[str, Norm] | None = None) -> DemandEstimate:
    norms = norms or NORMS
    days = published_days(db)
    if not days:
        raise ValueError("no published reports ingested")
    as_of = as_of or days[-1]
    if as_of not in set(days):
        raise ValueError(f"no successfully ingested report for {as_of}")

    circles: dict[tuple[str, str], CircleDemand] = {}
    district_totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    seen: dict[tuple[str, str, str], float] = {}

    metrics = [CAMP, CENTRE, f"{CAMP}_circle", f"{CENTRE}_circle", f"{AFFECTED}_circle"]
    for _d, district, place, metric, value in _rows(db, as_of, metrics):
        value = value or 0.0
        if metric in (CAMP, CENTRE):
            district_totals[district][metric] = max(district_totals[district][metric], value)
            continue

        base = metric.removesuffix("_circle")
        key = (district, place)
        c = circles.setdefault(key, CircleDemand(district=district, circle=place))
        prior = seen.get((district, place, base))
        if prior is not None and prior != value:
            # The same circle printed twice with different numbers. Keep the
            # larger -- under-supplying is the costlier error -- and say so.
            c.conflicts.append(f"{base}: {prior:g} and {value:g} both reported; using the larger")
            value = max(prior, value)
        seen[(district, place, base)] = value
        if base == CAMP:
            c.camp_inmates = value
        elif base == CENTRE:
            c.centre_inmates = value
        else:
            c.affected = value

    unattributed: dict[str, dict[str, float]] = {}
    for district, totals in district_totals.items():
        gap = {}
        for metric, attr in ((CAMP, "camp_inmates"), (CENTRE, "centre_inmates")):
            circle_sum = sum(getattr(c, attr) for (d, _), c in circles.items() if d == district)
            if totals.get(metric, 0.0) - circle_sum > 0.5:
                gap[metric] = round(totals[metric] - circle_sum, 1)
        if gap:
            unattributed[district] = gap

    places = gazetteer.load()
    for c in circles.values():
        r = gazetteer.resolve(c.circle, places)
        c.located_as, c.location_note = r.how, r.note
        if r.place:
            c.lon, c.lat = r.place.lon, r.place.lat

    ordered = sorted(circles.values(), key=lambda c: (-c.people, c.district, c.circle))
    return DemandEstimate(as_of, horizon_days, ordered, unattributed, norms)


def as_dict(e: DemandEstimate) -> dict:
    def circle(c: CircleDemand) -> dict:
        return {
            "district": c.district,
            "circle": c.circle,
            "people_to_supply": int(c.people),
            "camp_inmates": int(c.camp_inmates),
            "centre_inmates": int(c.centre_inmates),
            "population_affected": None if c.affected is None else int(c.affected),
            "needs": c.quantities(e.norms, e.horizon_days),
            "location": (
                {"lon": c.lon, "lat": c.lat, "resolved_by": c.located_as, "note": c.location_note}
                if c.lon is not None
                else None
            ),
            "location_problem": None if c.lon is not None else c.location_note,
            "conflicts": c.conflicts,
        }

    need_total = {
        k: round(sum(c.quantities(e.norms, e.horizon_days)[k] for c in e.circles), 1)
        for k in e.norms
    }
    return {
        "as_of": e.as_of.isoformat(),
        "horizon_days": e.horizon_days,
        "totals": {
            "people_to_supply": int(sum(c.people for c in e.circles)),
            "people_located": int(sum(c.people for c in e.located)),
            "people_unlocated": int(sum(c.people for c in e.unlocated)),
            "needs": need_total,
        },
        "circles": [circle(c) for c in e.circles if c.people > 0 or (c.affected or 0) > 0],
        "unattributed_by_district": e.unattributed,
        "norms": {
            k: {
                "label": n.label,
                "unit": n.unit,
                "per_person_per_day": n.per_person_per_day,
                "kg_per_unit": n.kg_per_unit,
                "urgency": n.urgency,
                "source": n.source,
                "basis": n.basis,
            }
            for k, n in e.norms.items()
        },
        "caveats": {
            "who_is_counted": (
                "People in relief camps plus people drawing from relief distribution "
                "centres, as reported. Population affected is shown for context and is "
                "not planned for."
            ),
            "where": (
                "Demand is placed at each revenue circle's headquarters town from "
                "OpenStreetMap, not at camp locations, which are not published."
            ),
            "urgency": URGENCY_NOTE,
            "not_included": "Medical supplies: no defensible per-person daily quantity.",
        },
    }
