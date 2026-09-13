"""
The district-day table the Phase 3 model learns from.

WHAT IS BEING PREDICTED, AND WHY NOT ROAD DAMAGE
The obvious target is "will this road be damaged". It is not usable, for two
reasons found in the data rather than assumed:

  Too few.        Geolocated damage inside the corridor numbers in the single
                  digits. A per-road model trained on that would be theatre.

  Dated wrongly   DRIMS damage rows carry the date they were *reported*, not
  for this.       the date the damage happened. One Cachar row records rain on
                  20 July that reached the report on 12 August. Forecasting
                  those rows forecasts paperwork.

What the report does publish promptly, every day, for every district in the
state, is **whether the district is flood-affected**. That is the target:
`affected(district, day + h)`. It is statewide, so there are thousands of
examples rather than a handful, and it is timely, so predicting it means
something.

WHAT COUNTS AS A NEGATIVE
A district is "not affected" on a day only when a report was actually
published that day and the district is absent from it. A day with no report
is unknown, not quiet -- treating it as quiet would teach the model that
floods end whenever the portal is down.

EVERYTHING HERE IS PURE
Rows come in, rows go out. No database, no network, so the rules above are
unit-tested directly.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.ingestion.districts import normalise_district

# The metrics that describe a district's flood state on a report day.
AFFECTED_METRICS = {"district_reported_affected", "population_affected", "villages_affected"}
INFRA_METRICS = {"roads_damaged", "bridges_damaged", "embankments_breached"}
USED_METRICS = AFFECTED_METRICS | INFRA_METRICS | {"relief_camps_opened"}

FEATURES = (
    "affected",             # listed as affected today
    "log_population",       # log1p(people affected today)
    "affected_frac_7d",     # share of published reports in the last 7 days listing it
    "run_length",           # consecutive affected reports ending today, /14, capped
    "population_trend",     # change in log1p(population) since the previous report
    "relief_camps_open",    # any relief camp open today
    "infra_damage_7d",      # any road/bridge/embankment damage reported in 7 days
    "affected_frac_60d",    # longer-run flood-proneness, excluding today
    "state_log_affected",   # log1p(districts affected statewide today)
    "state_trend",          # change in that since the previous report
)


def district_key(place_name: str | None) -> str | None:
    """A stable key for a district as the report prints it.

    Corridor districts use their canonical name so they join to the road
    graph. Everything else is squashed to lowercase letters, which is what
    repairs the PDF's mid-word line breaks: "Bongaigao n" and "Bongaigaon"
    are the same district and must not become two.
    """
    if not place_name:
        return None
    canonical = normalise_district(place_name)
    if canonical:
        return canonical
    squashed = re.sub(r"[^a-z]", "", place_name.lower())
    return squashed or None


@dataclass
class DayState:
    affected: bool = False
    population: float = 0.0
    relief_camps: float = 0.0
    infra_damage: bool = False


@dataclass
class ReportHistory:
    """Every district's state on every day a report was published."""

    published: list[date]
    states: dict[tuple[str, date], DayState]
    districts: list[str]
    display_names: dict[str, str] = field(default_factory=dict)

    def state(self, key: str, day: date) -> DayState | None:
        """None when no report was published that day -- unknown, not quiet."""
        if day not in self._published_set:
            return None
        return self.states.get((key, day), DayState())

    def __post_init__(self) -> None:
        self._published_set = set(self.published)


def build_history(
    published_days: list[date],
    observations: list[tuple[date, str | None, str, float | None]],
) -> ReportHistory:
    """Collapse raw observation rows into per-district daily states.

    `observations` are (report_date, place_name, metric, value_num).
    `published_days` are days with a successfully parsed report; observations
    on any other day are ignored, because a day we cannot vouch for as
    complete cannot supply negatives.
    """
    published = sorted(set(published_days))
    published_set = set(published)
    states: dict[tuple[str, date], DayState] = defaultdict(DayState)
    display: dict[str, str] = {}

    for day, place, metric, value in observations:
        if day not in published_set or metric not in USED_METRICS:
            continue
        key = district_key(place)
        if key is None:
            continue
        display.setdefault(key, normalise_district(place) or " ".join((place or "").split()))
        s = states[(key, day)]
        v = value or 0.0
        if metric == "district_reported_affected":
            s.affected = s.affected or v > 0
        elif metric == "population_affected":
            s.population = max(s.population, v)
            s.affected = s.affected or v > 0
        elif metric == "villages_affected":
            s.affected = s.affected or v > 0
        elif metric == "relief_camps_opened":
            s.relief_camps = max(s.relief_camps, v)
        elif metric in INFRA_METRICS and v > 0:
            s.infra_damage = True

    districts = sorted({k for k, _ in states})
    return ReportHistory(published, dict(states), districts, display)


def _previous_published(history: ReportHistory, day: date, within_days: int) -> date | None:
    for back in range(1, within_days + 1):
        d = day - timedelta(days=back)
        if d in history._published_set:
            return d
    return None


def features_for(history: ReportHistory, key: str, day: date) -> dict[str, float] | None:
    """Features for one district on one report day, using only reports up to
    and including that day. None when that day has no report."""
    today = history.state(key, day)
    if today is None:
        return None

    window7 = [history.state(key, day - timedelta(days=b)) for b in range(7)]
    window7 = [s for s in window7 if s is not None]
    window60 = [history.state(key, day - timedelta(days=b)) for b in range(1, 61)]
    window60 = [s for s in window60 if s is not None]

    run = 0
    for b in range(0, 60):
        s = history.state(key, day - timedelta(days=b))
        if s is None:
            continue  # a missing report neither extends nor breaks a run
        if not s.affected:
            break
        run += 1

    prev_day = _previous_published(history, day, within_days=3)
    prev = history.state(key, prev_day) if prev_day else None

    def state_count(d: date) -> int:
        return sum(1 for k in history.districts if history.states.get((k, d), DayState()).affected)

    n_today = state_count(day)
    n_prev = state_count(prev_day) if prev_day else n_today

    return {
        "affected": float(today.affected),
        "log_population": math.log1p(today.population),
        "affected_frac_7d": sum(s.affected for s in window7) / len(window7),
        "run_length": min(run, 14) / 14.0,
        "population_trend": (
            math.log1p(today.population) - math.log1p(prev.population) if prev else 0.0
        ),
        "relief_camps_open": float(today.relief_camps > 0),
        "infra_damage_7d": float(any(s.infra_damage for s in window7)),
        "affected_frac_60d": (
            sum(s.affected for s in window60) / len(window60) if window60 else 0.0
        ),
        "state_log_affected": math.log1p(n_today),
        "state_trend": math.log1p(n_today) - math.log1p(n_prev),
    }


@dataclass
class Example:
    district: str
    as_of: date
    target_date: date
    x: list[float]
    y: int
    affected_today: int


def build_examples(history: ReportHistory, horizon_days: int) -> list[Example]:
    """One example per (district, report day) whose target day also has a
    published report. Days whose outcome is unknown are skipped, not guessed."""
    out: list[Example] = []
    for day in history.published:
        target = day + timedelta(days=horizon_days)
        if target not in history._published_set:
            continue
        for key in history.districts:
            f = features_for(history, key, day)
            outcome = history.state(key, target)
            if f is None or outcome is None:
                continue
            out.append(
                Example(
                    district=key,
                    as_of=day,
                    target_date=target,
                    x=[f[name] for name in FEATURES],
                    y=int(outcome.affected),
                    affected_today=int(f["affected"]),
                )
            )
    return out
