from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencias import require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.reporte import ReporteRequest, ReporteResponse, ReporteVozRequest, ReporteVozResponse
from app.servicios.reporte_gemini_service import ReporteGeminiService
from app.servicios.reporte_service import ReporteService

router = APIRouter(prefix="/reports", tags=["Dashboards and Reports (CU19)"])


@router.post(
    "/generate",
    response_model=ReporteResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar un reporte empresarial con filtros manuales",
)
def generate_report(
    payload: ReporteRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return ReporteService.generate(db=db, request=payload, user=current_user)


@router.post(
    "/voice",
    response_model=ReporteVozResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpretar una consulta de voz con Gemini y generar el reporte",
)
def generate_voice_report(
    payload: ReporteVozRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    from app.servicios.saas_service import enforce_subscription
    enforce_subscription(db, db.info.get("tenant_id"), ai=True)
    interpretation, report = ReporteGeminiService.generate(db=db, transcript=payload.transcript, user=current_user, branch_id=payload.branch_id)
    return ReporteVozResponse(
        transcript=payload.transcript,
        interpretation=interpretation,
        report=report,
    )
