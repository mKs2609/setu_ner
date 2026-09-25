"""
Visualize the baseline accessibility score across the Barak Valley corridor.

Colors every scored road edge by its baseline_accessibility value
(green = higher baseline accessibility, red = lower / more historically
flood-affected + bridge-penalized). Unscored edges -- the Meghalaya
portion of the corridor, outside our four Assam district boundaries --
are shown in light gray, not omitted, so the actual coverage gap stays
visible instead of quietly disappearing.

Static image (matplotlib), not an interactive map -- deliberately, for
reliability. An interactive MapLibre version is what the real product
gets later (apps/web); this is a quick, dependency-light way to actually
look at the result of today's work.

RUN THIS LOCALLY, from geo/osm where edges_with_baseline_accessibility.geojson
already exists.

    pip install matplotlib   (geopandas already installed)
    python visualize_baseline_accessibility.py

Output: baseline_accessibility_map.png in the same folder.
"""

import sys
from pathlib import Path

try:
    import geopandas as gpd
    import matplotlib.pyplot as plt
except ImportError:
    print("Missing dependencies. Run: pip install matplotlib")
    sys.exit(1)

HERE = Path(__file__).parent
INPUT_PATH = HERE / "edges_with_baseline_accessibility.geojson"
DISTRICTS_PATH = HERE / "districts.geojson"  # optional overlay, skipped if missing
OUTPUT_PATH = HERE / "baseline_accessibility_map.png"


def main():
    if not INPUT_PATH.exists():
        print(f"Missing {INPUT_PATH.name}. Run compute_baseline_accessibility.py first.")
        sys.exit(1)

    print("Loading edges...")
    edges = gpd.read_file(INPUT_PATH)

    scored = edges[edges["baseline_accessibility"].notna()]
    unscored = edges[edges["baseline_accessibility"].isna()]
    print(f"Plotting {len(scored)} scored edges and {len(unscored)} unscored edges...")

    fig, ax = plt.subplots(figsize=(14, 12))

    if DISTRICTS_PATH.exists():
        districts = gpd.read_file(DISTRICTS_PATH)
        districts.boundary.plot(ax=ax, color="black", linewidth=0.8, alpha=0.4, zorder=1)

    if len(unscored) > 0:
        unscored.plot(ax=ax, color="#cccccc", linewidth=0.5, zorder=2, label="No district match (outside coverage)")

    if len(scored) > 0:
        scored.plot(
            ax=ax,
            column="baseline_accessibility",
            cmap="RdYlGn",
            vmin=0, vmax=1,
            linewidth=0.8,
            zorder=3,
            legend=True,
            legend_kwds={"label": "Baseline accessibility (0 = worst, 1 = best)", "shrink": 0.6},
        )

    ax.set_title(
        "SetuNER \u2014 Baseline Accessibility, Barak Valley Corridor\n"
        "(district 2025 flood severity \u00d7 bridge factor \u2014 see compute_baseline_accessibility.py for method)",
        fontsize=12,
    )
    ax.set_axis_off()

    if len(unscored) > 0:
        ax.legend(loc="lower left", fontsize=9)

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH, dpi=200, bbox_inches="tight")
    print(f"\nSaved: {OUTPUT_PATH.name}")
    print("Open it to actually look at the result.")


if __name__ == "__main__":
    main()