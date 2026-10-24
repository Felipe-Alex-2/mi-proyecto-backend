from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user
from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.esquemas.recomendacion import RecomendacionRequest, RecomendacionResponse
from app.servicios.recomendacion_service import RecomendacionService
from app.servicios.bitacora_service import BitacoraService

router = APIRouter(prefix="/recommendations", tags=["AI Recommendations"])


@router.post(
    "/chat",
    response_model=RecomendacionResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpretar gustos del cliente y recomendar prendas del catálogo",
)
def recommend_products(
    payload: RecomendacionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = RecomendacionService.recommend(db=db, message=payload.message)
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="CONSULTA_IA_CARLITOS",
        description=f"Consulta al Asistente Carlitos: '{payload.message[:80]}' (Coincidencias: {len(result.recommendations)} prendas)",
        category="IA",
    )
    return result
