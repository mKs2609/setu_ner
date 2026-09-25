"""
A first BASELINE accessibility score per edge.

Deliberately simple and rule-based, not ML -- this is the thing a future
trained model (Model A) has to actually beat, matching the "establish a
strong baseline first" discipline from the project's evaluation approach
(docs/decisions/0001-gap-analysis-and-enhancements.md).

FORMULA (and why each part is there):
  baseline_accessibility = (1 - hist_flood_severity_2025) * bridge_factor

  - (1 - hist_flood_severity_2025): district's 2025 severity, inverted so
    higher severity means lower accessibility. Ranges 0-1.
  - bridge_factor: 0.7 for bridge edges, 1.0 otherwise. This is an
    ASSUMPTION, not derived from data -- flagged clearly as such, because
    the project committed to no fabricated numbers. It's motivated by real
    events, not invented from nothing: the corridor's two headline
    disruptions (the 2022 Bethukandi dyke breach and the 2025 Silchar-
    Kalain bridge collapse) were both infrastructure failures at specific
    crossing points, not generic road segments -- so weighting bridges as
    more fragile has a real basis, but the exact multiplier (0.7) is a
    placeholder pending real calibration once enough bridge-failure events
    are in the historical-replay dataset to fit one properly.

Every score also gets a "confidence" field. It's LOW for everything here,
on purpose -- this is annual, district-level, retrospective data, not a
live per-road signal. Making that visible in the data itself (not just in
a docstring) is what keeps the observed/derived/simulated distinction from
docs/decisions/0001 section 2.3 real instead of theoretical.

Edges with no district match (the Meghalaya portion of the corridor) get
no score, not a guessed default -- unknown stays unknown.

RUN THIS LOCALLY, from geo/osm where edges_with_hazard_context.geojson
already exists (no network needed).

    python compute_baseline_accessibility.py
"""

import sys
from pathlib import Path

try:
    import geopandas as gpd
except ImportError:
    print("Missing dependencies: pip install geopandas")
    sys.exit(1)

HERE = Path(__file__).parent
INPUT_PATH = HERE / "edges_with_hazard_context.geojson"
OUTPUT_PATH = HERE / "edges_with_baseline_accessibility.geojson"

BRIDGE_FACTOR = 0.7  # ASSUMPTION -- see module docstring. Not calibrated yet.


def compute_score(row) -> tuple[float | None, str]:
    severity = row.get("hist_flood_severity_2025")
    if severity is None or (isinstance(severity, float) and severity != severity):  # NaN check without pandas dependency here
        return None, "no_district_match"

    base = 1.0 - severity
    factor = BRIDGE_FACTOR if row.get("is_bridge") else 1.0
    score = base * factor
    score = max(0.0, min(1.0, score))  # clamp, defensive
    return score, "district_2025_severity_x_bridge_factor"


def main():
    if not INPUT_PATH.exists():
        print(f"Missing {INPUT_PATH.name}. Run assign_district_hazard_context.py first.")
        sys.exit(1)

    print("Loading edges with hazard context...")
    edges = gpd.read_file(INPUT_PATH)

    scores = []
    bases = []
    confidences = []
    for _, row in edges.iterrows():
        score, basis = compute_score(row)
        scores.append(score)
        bases.append(basis)
        confidences.append("low" if score is not None else None)

    edges["baseline_accessibility"] = scores
    edges["baseline_accessibility_basis"] = bases
    edges["baseline_accessibility_confidence"] = confidences

    edges.to_file(OUTPUT_PATH, driver="GeoJSON")

    scored = edges["baseline_accessibility"].notna()
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total edges: {len(edges)}")
    print(f"Scored: {scored.sum()} ({scored.sum() / len(edges) * 100:.0f}%)")
    if scored.sum() > 0:
        scored_vals = edges.loc[scored, "baseline_accessibility"]
        print(f"Score range: {scored_vals.min():.2f} - {scored_vals.max():.2f}")
        print(f"Mean: {scored_vals.mean():.2f}")

        bridge_edges = edges[scored & edges["is_bridge"]]
        non_bridge_edges = edges[scored & ~edges["is_bridge"]]
        if len(bridge_edges) and len(non_bridge_edges):
            print(f"\nBridge edges ({len(bridge_edges)}): mean score {bridge_edges['baseline_accessibility'].mean():.2f}")
            print(f"Non-bridge edges ({len(non_bridge_edges)}): mean score {non_bridge_edges['baseline_accessibility'].mean():.2f}")
            print("(bridge edges should score lower -- that's the bridge_factor penalty applying)")

    print(f"\nSaved: {OUTPUT_PATH.name}")
    print(
        "\nThis is a baseline, not a model -- every score is traceable to "
        "exactly two real inputs (2025 district severity + bridge flag) and "
        "one documented assumption (the bridge factor). That traceability "
        "is the point: it's what 'why this route?' in the explanation "
        "drawer will eventually answer for real predictions too."
    )


if __name__ == "__main__":
    main()