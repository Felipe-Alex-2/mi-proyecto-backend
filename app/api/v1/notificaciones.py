from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.api.dependencias import get_current_user
from app.esquemas.notificacion import NotificacionResponse, EstadisticasNotificacionResponse
from app.servicios.notificacion_service import NotificacionService

router = APIRouter(prefix="/notifications", tags=["Notificaciones"])


@router.get("", response_model=List[NotificacionResponse])
def get_user_notifications(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista las notificaciones del usuario actual."""
    return NotificacionService.list_user_notifications(db=db, user=current_user)


@router.get("/unread-count", response_model=EstadisticasNotificacionResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Retorna la cantidad de notificaciones no leídas."""
    count = NotificacionService.get_unread_count(db=db, user=current_user)
    return EstadisticasNotificacionResponse(unread_count=count)


@router.patch("/{id}/read", response_model=NotificacionResponse)
def mark_notification_as_read(
    id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Marca una notificación específica como leída."""
    return NotificacionService.mark_as_read(db=db, user=current_user, notification_id=id)


@router.patch("/read-all", status_code=status.HTTP_200_OK)
def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Marca todas las notificaciones del usuario como leídas."""
    marked = NotificacionService.mark_all_as_read(db=db, user=current_user)
    return {"marked_read": marked}
