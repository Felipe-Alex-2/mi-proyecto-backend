from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencias import require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.reporte import ReporteRequest, ReporteResponse, ReporteVozRequest, ReporteVozResponse, ReporteCorreo
from app.servicios.reporte_gemini_service import ReporteGeminiService
from app.servicios.reporte_service import ReporteService

router = APIRouter(prefix="/reports", tags=["Dashboards and Reports (CU19)"])
report_reader = require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER, RolUsuario.CASHIER, RolUsuario.CUSTOMER)


@router.get('/dashboard')
def dashboard_summary(
    months: int = Query(1, ge=1, le=12),
    branch_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    from app.servicios.panel_service import dashboard
    if months not in (1, 3, 12):
        raise HTTPException(422, 'Selecciona un periodo de 1, 3 o 12 meses.')
    return dashboard(db, current_user, months, branch_id)


@router.post(
    "/generate",
    response_model=ReporteResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar un reporte empresarial con filtros manuales",
)
def generate_report(
    payload: ReporteRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(report_reader),
):
    from app.servicios.reporte_entrega_service import finish
    report=ReporteService.generate(db=db, request=payload, user=current_user)
    return finish(db,current_user,report,payload)


@router.post(
    "/voice",
    response_model=ReporteVozResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpretar una consulta de voz con Gemini y generar el reporte",
)
def generate_voice_report(
    payload: ReporteVozRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(report_reader),
):
    from app.servicios.saas_service import enforce_subscription
    from app.servicios.reporte_entrega_service import finish
    if not current_user.is_saas_admin:
        enforce_subscription(db, db.info.get("tenant_id"), ai=True)
    interpretation, report = ReporteGeminiService.generate(db=db, transcript=payload.transcript, user=current_user, branch_id=payload.branch_id, all_companies=payload.all_companies)
    report=finish(db,current_user,report,payload)
    return ReporteVozResponse(transcript=payload.transcript,interpretation=interpretation,report=report)


@router.get('/{id}/pdf')
def download_pdf(id:str,db:Session=Depends(get_db),current_user:Usuario=Depends(report_reader)):
    from fastapi.responses import Response
    from app.servicios.reporte_entrega_service import owned,pdf,response
    row=owned(db,current_user,id)
    return Response(pdf(response(row)),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="reporte-vesta.pdf"'})


@router.post('/{id}/email',response_model=ReporteResponse)
def send_email(id:str,payload:ReporteCorreo,db:Session=Depends(get_db),current_user:Usuario=Depends(report_reader)):
    from app.servicios.reporte_entrega_service import owned,deliver
    recipient=current_user.email if payload.email_self else payload.email_to
    if not recipient:raise HTTPException(422,'Indica el correo de destino.')
    return deliver(db,owned(db,current_user,id),str(recipient))
