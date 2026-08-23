"""
Public, read-only accessibility API.

Deliberately separate from the operator-facing endpoints above: no auth,
rate-limited, minimal fields only. This is what lets NGOs, other apps, or a
future consumer map product query "is this road passable right now" without
needing an account -- see docs/decisions/0001 §7 Tier 3, item 9.

Keep this endpoint's response shape stable once it ships; treat it like a
public contract, not an internal implementation detail.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/accessibility/{road_id}")
def public_accessibility(road_id: str):
    # TODO: same underlying data as /api/v1/accessibility, but trimmed to
    # {road_id, status, last_updated} only -- no confidence internals, no
    # operator-only fields, no PII from field reports.
    return {
        "road_id": road_id,
        "status": None,
        "last_updated": None,
        "note": "stub -- public contract, keep response shape minimal and stable",
    }
