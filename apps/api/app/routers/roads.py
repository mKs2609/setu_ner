"""Road graph: nodes, edges, current state. Backed by the dynamic road graph service."""
from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_roads():
    # TODO: query PostGIS road_state table once the graph is built (Phase 1)
    return {"roads": [], "note": "stub -- Phase 1 (static GIS + graph) not yet built"}
