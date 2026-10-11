"""
Saved recommendations, their explanations, and operator overrides.

    GET  /api/v1/recommendations                     recent saved plans
    GET  /api/v1/recommendations/{id}                the frozen record
    GET  /api/v1/recommendations/{id}/explanation    why the plan is what it is
    GET  /api/v1/recommendations/{id}/overrides      what operators did instead
    POST /api/v1/recommendations/{id}/overrides      record an override

A record is created by POST /api/v1/logistics/plan with "save": true. There
is no endpoint that changes one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Recommendation, RecommendationOverride
from app import security
from app.db.session import get_db
from app.services.explain import audit

router = APIRouter()


class OverrideIn(BaseModel):
    operator_id: str = Field(
        min_length=6, max_length=128,
        description="Opaque, device-scoped id -- not a name or phone number.",
    )
    action: str = Field(pattern="^(accepted|modified|rejected)$")
    reason_category: str = Field(
        pattern="^(" + "|".join(audit.REASON_CATEGORIES) + ")$"
    )
    reason: str = Field(
        min_length=5, max_length=1000,
        description="Required: an override without a reason teaches nothing.",
    )
    target: str | None = Field(None, max_length=200, description='e.g. "run:Silchar->Sonai"')


def _get(db: Session, rec_id: str) -> Recommendation:
    if len(rec_id) != 32 or not all(c in "0123456789abcdef" for c in rec_id):
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return rec


@router.get("")
def list_recommendations(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Saved plans and scenario runs, newest first.

    The audit trail: each record keeps the inputs and model versions it was
    built from, so a past decision can be read back as it was made.
    """
    recs = db.execute(
        select(Recommendation).order_by(Recommendation.created_at.desc()).limit(limit)
    ).scalars().all()
    counts = dict(
        db.execute(
            select(RecommendationOverride.recommendation_id, func.count(RecommendationOverride.id))
            .where(RecommendationOverride.recommendation_id.in_([r.id for r in recs]))
            .group_by(RecommendationOverride.recommendation_id)
        ).all()
    ) if recs else {}
    return {"recommendations": [audit.summary(r, counts.get(r.id, 0)) for r in recs]}


@router.get("/{rec_id}")
def get_recommendation(rec_id: str, db: Session = Depends(get_db)):
    """One saved record in full: inputs, outputs, model versions, data date.

    `data_as_of` is the report date the decision was built from, which is what
    makes an old record judgeable rather than merely old.
    """
    rec = _get(db, rec_id)
    return {
        **audit.summary(rec),
        "model_versions": rec.model_versions,
        "inputs": rec.inputs,
        "outputs": rec.outputs,
        "note": (
            "This record is frozen as it was saved. Reports, the model and depot stock have "
            "likely changed since; re-plan for current conditions rather than reusing it."
        ),
    }


@router.get("/{rec_id}/explanation")
def get_explanation(rec_id: str, db: Session = Depends(get_db)):
    """The explanation stored with a record, as it was written at the time.

    Replayed, not recomputed — regenerating it with today's model would
    describe a decision nobody actually made.
    """
    rec = _get(db, rec_id)
    return {"id": rec.id, "data_as_of": rec.data_as_of.isoformat(), **rec.explanation}


@router.get("/{rec_id}/overrides")
def list_overrides(rec_id: str, db: Session = Depends(get_db)):
    """Operator overrides recorded against this record, oldest first.

    An override never edits the original: both the recommendation and the
    human disagreement with it are kept, which is the point of the log.
    """
    rec = _get(db, rec_id)
    rows = db.execute(
        select(RecommendationOverride)
        .where(RecommendationOverride.recommendation_id == rec.id)
        .order_by(RecommendationOverride.created_at)
    ).scalars().all()
    return {"id": rec.id, "overrides": [audit.override_dict(o) for o in rows]}


@router.post(
    "/{rec_id}/overrides", status_code=201, dependencies=[Depends(security.require_operator)]
)
def add_override(rec_id: str, body: OverrideIn, db: Session = Depends(get_db)):
    """Record an operator's decision to do something other than what was advised.

    Needs an operator token. Appends to the record rather than changing it, so
    the system can later be asked which of its outputs people actually used —
    the question it cannot answer about itself.
    """
    rec = _get(db, rec_id)
    try:
        row = audit.add_override(
            db, rec,
            operator_id=body.operator_id, action=body.action,
            reason_category=body.reason_category, reason=body.reason.strip(),
            target=body.target,
        )
    except audit.RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return audit.override_dict(row)
