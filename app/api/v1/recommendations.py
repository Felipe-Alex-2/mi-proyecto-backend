from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse
from app.services.recommendation_service import RecommendationService
from app.services.activity_log_service import ActivityLogService

router = APIRouter(prefix="/recommendations", tags=["AI Recommendations"])


@router.post(
    "/chat",
    response_model=RecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpretar gustos del cliente y recomendar prendas del catálogo",
)
def recommend_products(
    payload: RecommendationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = RecommendationService.recommend(db=db, message=payload.message)
    ActivityLogService.log_event(
        db=db,
        user=current_user,
        action="CONSULTA_IA_CARLITOS",
        description=f"Consulta al Asistente Carlitos: '{payload.message[:80]}' (Coincidencias: {len(result.recommendations)} prendas)",
        category="IA",
    )
    return result
