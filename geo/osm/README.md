# geo/osm

Real OSM road-network extraction for the Barak Valley corridor.

Run locally (needs internet access to OSM's Overpass API):

    pip install -r requirements.txt
    python build_road_graph.py

Produces nodes.geojson, edges.geojson, road_graph.graphml in this folder.
Open edges.geojson at geojson.io afterward and check it against a real
map before trusting it -- the bounding box in the script is a first pass.