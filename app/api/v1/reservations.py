from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.reservation import (
    ReservationCreate,
    ReservationStatusUpdate,
    ReservationResponse,
    ReservationStatsResponse,
)
from app.services.reservation_service import ReservationService

router = APIRouter(prefix="/reservations", tags=["In-Store Try-On Reservations (CU13)"])


@router.post(
    "",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una nueva reserva para prueba presencial de prendas",
)
def create_reservation(
    payload: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ReservationService.create_reservation(db=db, customer=current_user, data=payload)


@router.get(
    "",
    response_model=List[ReservationResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar reservas (Clientes ven las suyas; Encargado/Cajero ven su sucursal; Admin ve todas)",
)
def list_reservations(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal (solo Admin)"),
    status: Optional[str] = Query(None, description="Filtrar por estado"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ReservationService.list_reservations(
        db=db,
        user=current_user,
        branch_id=branch_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats",
    response_model=ReservationStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Estadísticas generales de reservas y conversión (Admin / Encargado)",
)
def get_reservation_stats(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER)),
):
    return ReservationService.get_stats(db=db, user=current_user, branch_id=branch_id)


@router.get(
    "/{id}",
    response_model=ReservationResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle completo de una reserva",
)
def get_reservation(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ReservationService.get_reservation(db=db, reservation_id=id, user=current_user)


@router.patch(
    "/{id}/status",
    response_model=ReservationResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar estado de la reserva (Staff)",
)
def update_reservation_status(
    id: str,
    payload: ReservationStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER, UserRole.CASHIER)),
):
    return ReservationService.update_status(db=db, reservation_id=id, user=current_user, data=payload)


@router.delete(
    "/{id}",
    response_model=ReservationResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancelar una reserva propia (Cliente)",
)
def cancel_reservation(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ReservationService.cancel_by_customer(db=db, reservation_id=id, customer=current_user)
