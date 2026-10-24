from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencias import require_roles
from app.nucleo.ambito_sucursal import resolve_branch
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.bitacora import BitacoraListResponse
from app.servicios.bitacora_service import BitacoraService

router = APIRouter(prefix="/activity-logs", tags=["Activity Log"])


@router.get(
    "",
    response_model=BitacoraListResponse,
    summary="Consultar la bitácora completa del sistema",
)
def list_activity_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    action: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    branch_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return BitacoraService.list_logs(
        db=db,
        page=page,
        page_size=page_size,
        action=action,
        category=category,
        search=search,
        branch_id=resolve_branch(current_user, branch_id),
    )
