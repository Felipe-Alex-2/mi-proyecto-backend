import base64
import tempfile
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, File, Form
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
from app.services.idm_vton_client import (
    IDMVTONUnavailableError,
    run_tryon_from_bytes,
)

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


@router.post(
    "/idm-tryon",
    status_code=status.HTTP_200_OK,
    summary="Virtual Try-On real con IDM-VTON via Gradio (multipart)",
    description=(
        "Recibe la foto de la persona y la foto de la prenda como archivos multipart, "
        "los envía al modelo IDM-VTON (expuesto via ngrok) y devuelve la imagen "
        "resultante en base64. Si el servicio VTON no está disponible responde 503."
    ),
)
async def idm_virtual_tryon(
    person_image: UploadFile = File(..., description="Foto de la persona (JPG/PNG)"),
    garment_image: UploadFile = File(..., description="Foto de la prenda (JPG/PNG)"),
    garment_description: str = Form(default="", description="Descripción opcional de la prenda"),
    use_auto_mask: bool = Form(default=True, description="Usar auto-masking (recomendado)"),
    use_auto_crop: bool = Form(default=False, description="Usar auto-crop y resize"),
    denoise_steps: int = Form(default=30, ge=20, le=40, description="Pasos de denoising"),
    seed: int = Form(default=42, description="Semilla para reproducibilidad"),
    current_user: User = Depends(get_current_user),
):
    """Llama al servicio IDM-VTON Gradio y retorna la imagen resultado en base64."""
    person_bytes = await person_image.read()
    garment_bytes = await garment_image.read()

    if not person_bytes:
        raise HTTPException(status_code=400, detail="La imagen de la persona está vacía.")
    if not garment_bytes:
        raise HTTPException(status_code=400, detail="La imagen de la prenda está vacía.")

    person_filename = person_image.filename or "person.jpg"
    garment_filename = garment_image.filename or "garment.jpg"

    try:
        result_bytes = run_tryon_from_bytes(
            person_image_bytes=person_bytes,
            person_filename=person_filename,
            garment_image_bytes=garment_bytes,
            garment_filename=garment_filename,
            garment_description=garment_description,
            use_auto_mask=use_auto_mask,
            use_auto_crop=use_auto_crop,
            denoise_steps=denoise_steps,
            seed=seed,
        )
    except IDMVTONUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"El servicio de Virtual Try-On (IDM-VTON) no está disponible. "
                f"Verifica que el modelo esté corriendo y VTON_URL esté configurada. "
                f"Detalle: {exc}"
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Error al procesar el Virtual Try-On. El servicio puede estar ocupado. "
                f"Intenta de nuevo en unos momentos. Detalle: {exc}"
            ),
        )

    result_b64 = base64.b64encode(result_bytes).decode("utf-8")
    return {
        "result_image_b64": result_b64,
        "mime_type": "image/webp",
        "message": "Virtual Try-On generado exitosamente con IDM-VTON.",
    }


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
