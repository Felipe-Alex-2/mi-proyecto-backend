from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.activity_log import ActivityLogCreate, ActivityLogListResponse, ActivityLogResponse
from app.services.activity_log_service import ActivityLogService

router = APIRouter(prefix="/activity-logs", tags=["Activity Log"])


@router.post(
    "",
    response_model=ActivityLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una actividad relevante del usuario actual",
)
def create_activity_log(
    payload: ActivityLogCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ActivityLogService.create(db=db, user=current_user, payload=payload, request=request)


@router.get(
    "",
    response_model=ActivityLogListResponse,
    summary="Consultar la bitácora completa del sistema",
)
def list_activity_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    action: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
):
    return ActivityLogService.list_logs(
        db=db,
        page=page,
        page_size=page_size,
        action=action,
        category=category,
        search=search,
    )
