"""Recommendations + explanations. Every recommendation should carry a traceable explanation record."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/{recommendation_id}")
def get_recommendation(recommendation_id: str):
    return {"id": recommendation_id, "recommendation": None, "note": "stub"}


@router.get("/{recommendation_id}/explanation")
def get_explanation(recommendation_id: str):
    # TODO: plain-language explanation generation on top of SHAP + optimization trade-offs
    # (gap-analysis §7 Tier 2 item 8)
    return {"id": recommendation_id, "explanation": None, "note": "stub"}
