"""Region metadata: NER states/districts, boundaries, the locked study corridor."""
from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_regions():
    # TODO: replace with real PostGIS query once the corridor is locked (docs/decisions/0002)
    return {"regions": [], "note": "stub -- awaiting corridor decision, see docs/decisions/0002"}
