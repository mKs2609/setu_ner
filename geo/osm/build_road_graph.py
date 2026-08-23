"""
Phase 1: static road graph for the Barak Valley corridor.

Pulls the real OSM drivable road network and shapes it into the edge
schema the rest of the pipeline expects: road class, bridge flag,
baseline travel time, plus placeholder columns for fields later phases
fill in (current/predicted accessibility, hazard exposure, confidence).

RUN THIS LOCALLY -- it needs real internet access to OSM's Overpass API.

    pip install -r requirements.txt
    python build_road_graph.py

Public Overpass servers are shared community infrastructure and can be
flaky (timeouts, 502s, 500s). This version tries several known mirrors
automatically with retries, so you run it once and let it work through
failures itself instead of manually swapping URLs by hand.

OUTPUT
------
    nodes.geojson       -- road junctions/decision points
    edges.geojson        -- road segments with the enriched schema
    road_graph.graphml    -- full NetworkX graph, ready for later phases

IMPORTANT: bounding-box extraction is a first pass, not a final answer.
Open edges.geojson in geojson.io afterward and eyeball it against a real
map before trusting it.
"""

import sys
import time
from pathlib import Path

try:
    import osmnx as ox
    import geopandas as gpd
    import networkx as nx
    import pandas as pd
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

# --- Bounding box ------------------------------------------------------
# Currently the SMALL test box (central Silchar) so we confirm the
# pipeline works end to end before spending minutes on the full corridor.
# Once this succeeds, swap in the real corridor box (commented below)
# and re-run.
# NORTH, SOUTH, EAST, WEST = 24.85, 24.80, 92.80, 92.75

# Real corridor box -- Cachar + Dima Hasao + the NH-6 stretch through
# Meghalaya. Swap to this once the small box has proven the pipeline works:
NORTH, SOUTH, EAST, WEST = 25.60, 24.60, 93.30, 92.00

OUTPUT_DIR = Path(__file__).parent

# Mirrors to try in order. overpass.openstreetmap.fr is deliberately
# excluded -- it 403s unregistered scripted access outright, retrying it
# wastes time. If both of these fail repeatedly, that points to something
# blocking Overpass traffic generally on this network, not server flakiness.
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api",
    "https://overpass-api.de/api",
]
ATTEMPTS_PER_MIRROR = 2
RETRY_WAIT_SECONDS = 20

SPEED_BY_CLASS_KMH = {
    "motorway": 80, "trunk": 60, "primary": 50, "secondary": 40,
    "tertiary": 30, "unclassified": 25, "residential": 20, "service": 15,
}
DEFAULT_SPEED_KMH = 25


def simplify_highway_tag(value):
    if isinstance(value, list):
        return value[0]
    return value


def estimate_speed_kmh(road_class):
    return SPEED_BY_CLASS_KMH.get(road_class, DEFAULT_SPEED_KMH)


def is_bridge(value):
    if isinstance(value, list):
        return any(v not in (None, "no") and pd.notna(v) for v in value)
    if pd.isna(value):
        return False  # no bridge tag at all -- the overwhelming majority of roads
    return value not in (None, "no", False)


def fetch_graph_with_retries(bbox):
    """Try each mirror in turn, with a couple of attempts each, before
    giving up. Prints progress so it's obvious what's happening instead
    of sitting there silently."""
    last_error = None
    for mirror in OVERPASS_MIRRORS:
        ox.settings.overpass_url = mirror
        ox.settings.requests_timeout = 180
        for attempt in range(1, ATTEMPTS_PER_MIRROR + 1):
            print(f"-> Trying {mirror} (attempt {attempt}/{ATTEMPTS_PER_MIRROR})...")
            try:
                G = ox.graph_from_bbox(bbox=bbox, network_type="drive", simplify=True)
                print(f"   Success via {mirror}")
                return G
            except Exception as e:
                print(f"   Failed: {e}")
                last_error = e
                if attempt < ATTEMPTS_PER_MIRROR:
                    print(f"   Waiting {RETRY_WAIT_SECONDS}s before retrying...")
                    time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError(
        "All Overpass mirrors failed after retries. This points to something "
        "blocking Overpass traffic on this network generally, not one flaky "
        "server. Next step: try from a different network (phone hotspot is a "
        "quick test), or switch to a downloaded extract file instead of a "
        "live query."
    ) from last_error


def main():
    print(f"Fetching drivable road network for bbox N={NORTH} S={SOUTH} E={EAST} W={WEST}...\n")

    G = fetch_graph_with_retries((WEST, SOUTH, EAST, NORTH))

    print(f"\nRaw graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

    edges_gdf["road_class"] = edges_gdf["highway"].apply(simplify_highway_tag)
    edges_gdf["is_bridge"] = edges_gdf["bridge"].apply(is_bridge) if "bridge" in edges_gdf.columns else False
    edges_gdf["assumed_speed_kmh"] = edges_gdf["road_class"].apply(estimate_speed_kmh)
    edges_gdf["length_km"] = edges_gdf["length"] / 1000.0
    edges_gdf["baseline_travel_time_min"] = (
        edges_gdf["length_km"] / edges_gdf["assumed_speed_kmh"] * 60.0
    )

    edges_gdf["current_accessibility"] = None
    edges_gdf["predicted_accessibility"] = None
    edges_gdf["hazard_exposure"] = None
    edges_gdf["confidence"] = None
    edges_gdf["edge_type"] = "road"
    edges_gdf["scenario_state"] = "baseline"

    keep_cols = [
        "geometry", "road_class", "is_bridge", "length_km",
        "assumed_speed_kmh", "baseline_travel_time_min",
        "current_accessibility", "predicted_accessibility",
        "hazard_exposure", "confidence", "edge_type", "scenario_state",
        "name",
    ]
    keep_cols = [c for c in keep_cols if c in edges_gdf.columns]
    reset = edges_gdf.reset_index()
    extra = [c for c in ["u", "v", "key"] if c in reset.columns]
    edges_out = reset[keep_cols + extra]

    nodes_reset = nodes_gdf.reset_index()
    nodes_out = nodes_reset[["osmid", "geometry", "x", "y"]] if "osmid" in nodes_reset.columns else nodes_reset

    nodes_path = OUTPUT_DIR / "nodes.geojson"
    edges_path = OUTPUT_DIR / "edges.geojson"
    graphml_path = OUTPUT_DIR / "road_graph.graphml"

    nodes_out.to_file(nodes_path, driver="GeoJSON")
    edges_out.to_file(edges_path, driver="GeoJSON")
    ox.save_graphml(G, filepath=graphml_path)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Nodes: {len(nodes_out)}")
    print(f"Edges: {len(edges_out)}")
    print(f"Total road length: {edges_out['length_km'].sum():.1f} km")
    print(f"Bridge-flagged edges: {int(edges_out['is_bridge'].sum())}")
    print("\nBy road class:")
    print(edges_out["road_class"].value_counts().to_string())
    print(f"\nSaved: {nodes_path.name}, {edges_path.name}, {graphml_path.name}")


if __name__ == "__main__":
    main()