"""
Re-apply district normalisation to observations already stored.

    cd apps/api
    python -m app.services.ingestion.renormalise_districts

WHY THIS EXISTS
The DRIMS PDF wraps long table cells mid-word, so a report can print
"Cacha r", "Hailakand i" or "Sribhu mi". Until districts.py compared letters
only, those rows were stored with `district = NULL` -- invisible to
corroboration, to current-conditions routing, and to the Phase 3 labels,
which would have counted a flooded Cachar day as a dry one. Found while
building the model (docs/decisions/0010).

`place_name` keeps the source's spelling, so nothing needs re-fetching: the
district is recomputed from it. Only NULL districts are touched, and
`observation_key` does not include the district, so identities are unchanged.
Safe to run repeatedly.
"""

from __future__ import annotations

import sys

from sqlalchemy import select, update

from app.db.models import HazardObservation
from app.db.session import SessionLocal
from app.services.ingestion.districts import normalise_district


def renormalise(db) -> dict[str, int]:
    names = [
        n
        for (n,) in db.execute(
            select(HazardObservation.place_name)
            .where(
                HazardObservation.district.is_(None),
                HazardObservation.place_name.isnot(None),
            )
            .distinct()
        )
    ]
    repaired: dict[str, int] = {}
    for name in names:
        canonical = normalise_district(name)
        if canonical is None:
            continue
        result = db.execute(
            update(HazardObservation)
            .where(
                HazardObservation.district.is_(None),
                HazardObservation.place_name == name,
            )
            .values(district=canonical)
        )
        repaired[f"{name!r} -> {canonical}"] = result.rowcount or 0
    db.commit()
    return repaired


def main() -> int:
    with SessionLocal() as db:
        repaired = renormalise(db)
    if not repaired:
        print("nothing to repair")
    for label, n in repaired.items():
        print(f"{label}: {n} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
