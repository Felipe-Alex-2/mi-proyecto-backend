from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.notification import NotificationResponse, NotificationStatsResponse
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notificaciones"])


@router.get("", response_model=List[NotificationResponse])
def get_user_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista las notificaciones del usuario actual."""
    return NotificationService.list_user_notifications(db=db, user=current_user)


@router.get("/unread-count", response_model=NotificationStatsResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna la cantidad de notificaciones no leídas."""
    count = NotificationService.get_unread_count(db=db, user=current_user)
    return NotificationStatsResponse(unread_count=count)


@router.patch("/{id}/read", response_model=NotificationResponse)
def mark_notification_as_read(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca una notificación específica como leída."""
    return NotificationService.mark_as_read(db=db, user=current_user, notification_id=id)


@router.patch("/read-all", status_code=status.HTTP_200_OK)
def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca todas las notificaciones del usuario como leídas."""
    marked = NotificationService.mark_all_as_read(db=db, user=current_user)
    return {"marked_read": marked}
