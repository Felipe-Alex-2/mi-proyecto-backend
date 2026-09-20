from typing import Optional, List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User, UserRole
from app.models.virtual_fitting_session import VirtualFittingSession
from app.schemas.virtual_fitting import (
    BiometricProfileCreate,
    BiometricProfileResponse,
    SizeRecommendationRequest,
    SizeRecommendationResponse,
    TryOnRequest,
    TryOnResponse,
)
from app.services.virtual_fitting_service import VirtualFittingService

router = APIRouter(prefix="/virtual-fitting", tags=["Virtual Fitting Room (Probador Virtual con IA)"])


@router.get(
    "/profile",
    response_model=Optional[BiometricProfileResponse],
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil biométrico del cliente actual",
)
def get_biometric_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = VirtualFittingService.get_profile(db, current_user.id)
    return profile


@router.post(
    "/profile",
    response_model=BiometricProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Guardar o actualizar perfil biométrico del cliente",
)
def save_biometric_profile(
    payload: BiometricProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VirtualFittingService.upsert_profile(db, current_user.id, payload)


@router.post(
    "/recommend-size",
    response_model=SizeRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Calcular talla ideal con IA geométrica y porcentaje de confianza",
)
def recommend_size(
    payload: SizeRecommendationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VirtualFittingService.get_recommendation_for_user(
        db=db,
        user_id=current_user.id,
        product_id=payload.product_id,
        category_id=payload.category_id,
        custom_data=payload,
    )


@router.post(
    "/try-on",
    response_model=TryOnResponse,
    status_code=status.HTTP_200_OK,
    summary="Ejecutar prueba virtual de prenda (VTON)",
)
def try_on_garment(
    payload: TryOnRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VirtualFittingService.process_try_on(
        db=db,
        user_id=current_user.id,
        payload=payload,
    )


@router.get(
    "/sessions",
    response_model=List[TryOnResponse],
    status_code=status.HTTP_200_OK,
    summary="Obtener historial de pruebas del vestidor virtual",
)
def get_fitting_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = (
        db.query(VirtualFittingSession)
        .filter(VirtualFittingSession.user_id == current_user.id)
        .order_by(VirtualFittingSession.created_at.desc())
        .limit(20)
        .all()
    )
    results = []
    for s in sessions:
        results.append(
            TryOnResponse(
                session_id=s.id,
                result_image_url=s.result_image_url or "",
                user_image_url=s.user_image_url,
                garment_image_url=s.garment_image_url,
                recommended_size=s.recommended_size or "M",
                confidence_score=float(s.confidence_score or 90.0),
                fit_feedback="",
                fit_details=[],
                product_id=s.product_id,
                variant_id=s.variant_id,
                created_at=s.created_at,
            )
        )
    return results
