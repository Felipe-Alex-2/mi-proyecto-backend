from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.report import ReportRequest, ReportResponse, VoiceReportRequest, VoiceReportResponse
from app.services.gemini_report_service import GeminiReportService
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Dashboards and Reports (CU19)"])


@router.post(
    "/generate",
    response_model=ReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar un reporte empresarial con filtros manuales",
)
def generate_report(
    payload: ReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER)),
):
    return ReportService.generate(db=db, request=payload)


@router.post(
    "/voice",
    response_model=VoiceReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpretar una consulta de voz con Gemini y generar el reporte",
)
def generate_voice_report(
    payload: VoiceReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER)),
):
    interpretation, report = GeminiReportService.generate(db=db, transcript=payload.transcript)
    return VoiceReportResponse(
        transcript=payload.transcript,
        interpretation=interpretation,
        report=report,
    )
