"""
A supply plan, told in plain sentences, each carrying its evidence.

Every statement is built from numbers already in the plan response and
carries an `evidence` object pointing at them, so a reader who doubts a
sentence can check it against the figures rather than trust the wording.
Nothing here computes anything new -- an explanation that did its own
arithmetic could disagree with the plan it explains.

Statements are grouped the way an operator would read them: what the
situation is, what the plan does, what stops it doing more, and what it
leaves out.
"""

from __future__ import annotations


def _s(text: str, **evidence) -> dict:
    return {"text": text, "evidence": evidence}


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0%}"


def narrate(plan: dict) -> dict:
    demand, p, risk = plan["demand"], plan["plan"], plan["risk"]
    totals = demand["totals"]
    need = p["person_days_needed_all_commodities"]
    covered = p["person_days_covered_all_commodities"]
    coverage = covered / need if need else None

    situation = [
        _s(
            (f"Replay of the {plan['as_of']} report." if plan["is_replay"]
             else f"Live plan from the {plan['as_of']} report.")
            + f" {totals['people_to_supply']:,} people are in relief camps or drawing from "
            f"relief centres across the corridor.",
            as_of=plan["as_of"], people_to_supply=totals["people_to_supply"],
        ),
        _s(
            f"Over {demand['horizon_days']} day(s) they need {totals['needs']['water']:,.0f} litres of "
            f"water and {totals['needs']['food']:,.0f} ration-days of food, at "
            f"{demand['norms']['water']['per_person_per_day']:g} L and "
            f"{demand['norms']['food']['per_person_per_day']:g} ration-day per person per day.",
            needs=totals["needs"], norms={k: v["per_person_per_day"] for k, v in demand["norms"].items()},
        ),
    ]
    if plan["example_inputs"]:
        situation.append(_s(
            "Depot stock and trucks are the example figures, so this is a demonstration of the "
            "method, not a plan for real depots.",
            example_inputs=True,
        ))

    outcome = []
    if p["status"] == "nothing_to_supply":
        outcome.append(_s("Nobody reachable needs supplying on this day.", status=p["status"]))
    elif p["status"] != "optimal":
        outcome.append(_s("The optimiser did not find a plan.", status=p["status"]))
    else:
        policy = (
            "every circle was given the same shortfall fraction first, then as much need as possible covered"
            if p["policy"] == "fairness_first"
            else "as much urgency-weighted need as possible was covered first, then the remaining shortfall spread as evenly as possible"
        )
        outcome.append(_s(
            f"The plan covers {_pct(coverage)} of need at reachable circles; the worst-off circle "
            f"is {_pct(p['worst_shortfall_fraction'])} short. Priority: {policy}.",
            coverage=round(coverage, 4) if coverage is not None else None,
            worst_shortfall_fraction=p["worst_shortfall_fraction"], policy=p["policy"],
        ))
        outcome.append(_s(
            f"It uses {len(p['runs'])} depot-to-circle run(s) and about {p['truck_hours']:,.1f} truck-hours.",
            runs=len(p["runs"]), truck_hours=p["truck_hours"],
        ))

    routes = []
    penalty = risk["risk_minutes_per_exposure_km"]
    diverging = [r for r in plan["routes"] if r["used_in_plan"] and r["routes_diverge"]]
    if penalty > 0 and diverging:
        worth = sorted(
            diverging,
            key=lambda r: -((r["fastest"]["exposure_km"] or 0) - (r["lower_exposure"]["exposure_km"] or 0)),
        )[:3]
        for r in worth:
            f, s = r["fastest"], r["lower_exposure"]
            routes.append(_s(
                f"{r['depot']} → {r['circle']} takes the lower-exposure route: "
                f"{s['travel_min'] - f['travel_min']:+.0f} min for "
                f"{f['exposure_km'] - s['exposure_km']:.1f} fewer exposure-km "
                f"({f['bridges']} → {s['bridges']} bridges).",
                depot=r["depot"], circle=r["circle"], fastest=f, lower_exposure=s,
            ))
        routes.append(_s(
            f"Routes trade up to {penalty:g} minutes of detour for each exposure-km avoided — the "
            f"setting you chose. Exposure-km weights distance by how inaccessible the forecast "
            f"rates each road ({risk['accessibility_source']}).",
            risk_minutes_per_exposure_km=penalty, accessibility_source=risk["accessibility_source"],
        ))
    elif penalty == 0:
        routes.append(_s("Every run takes the fastest route; exposure to at-risk roads was not weighed.",
                         risk_minutes_per_exposure_km=0))
    if risk["live_conditions_applied"] and (risk["closed_roads"] or risk["degraded_roads"]):
        routes.append(_s(
            f"Live reports close {risk['closed_roads']} road segment(s) and slow "
            f"{risk['degraded_roads']}; routes avoid or account for them.",
            closed_roads=risk["closed_roads"], degraded_roads=risk["degraded_roads"],
        ))

    limits = [_s(l["plain"], **{k: v for k, v in l.items() if k != "plain"}) for l in p["limits"]]
    if p["status"] == "optimal" and not limits and p["shortfalls"]:
        limits.append(_s("Shortfalls remain only where no depot has a route.",
                         shortfalls=len(p["shortfalls"])))

    left_out = []
    unreachable = sorted({s["circle"] for s in p["shortfalls"] if s["reason"].startswith("no depot")})
    if unreachable:
        left_out.append(_s(
            f"No depot has a route to {', '.join(unreachable)}; nothing is sent there.",
            circles=unreachable,
        ))
    if p.get("people_outside_plan"):
        left_out.append(_s(
            f"{p['people_outside_plan']:,} people are at circles the plan cannot place on the road "
            "graph and are not included in the coverage figure.",
            people_outside_plan=p["people_outside_plan"], problems=plan["problems"],
        ))
    for district, gap in demand["unattributed_by_district"].items():
        left_out.append(_s(
            f"{district} reports {sum(gap.values()):,.0f} people it does not assign to any revenue "
            "circle, so they cannot be routed to.",
            district=district, unattributed=gap,
        ))
    if p.get("omitted_residue_kg"):
        left_out.append(_s(
            f"{p['omitted_residue_kg']:.1f} kg of sub-kilogram solver residue was omitted from the runs.",
            omitted_residue_kg=p["omitted_residue_kg"],
        ))

    return {
        "summary": " ".join(x["text"] for x in (situation[:1] + outcome[:1] + limits[:1])),
        "sections": [
            {"title": "Situation", "statements": situation},
            {"title": "What the plan does", "statements": outcome},
            {"title": "Route choices", "statements": routes},
            {"title": "What limits it", "statements": limits},
            {"title": "Left out", "statements": left_out},
        ],
        "method": (
            "Every sentence is filled in from the plan's own figures, which each statement's "
            "evidence repeats. No text is generated freely and nothing is recalculated."
        ),
    }
