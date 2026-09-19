from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentPayPalOrderResponse,
    PendingReservationOption,
    PaymentProcess,
)
from app.services.payment_service import PaymentService
from app.api.deps import get_current_user

router = APIRouter(prefix="/payments", tags=["Caja y Pagos (POS)"])


@router.get("", response_model=List[PaymentResponse])
def list_payments(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrar por estado (PENDING, PAID, CANCELLED)"),
    payment_type: Optional[str] = Query(None, description="Filtrar por tipo (EFECTIVO, PAYPAL)"),
    search: Optional[str] = Query(None, description="Búsqueda por cliente, código o concepto"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista transacciones de caja e historial de cobros."""
    return PaymentService.list_payments(
        db=db,
        user=current_user,
        branch_id=branch_id,
        status=status_filter,
        payment_type=payment_type,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/pending-reservations", response_model=List[PendingReservationOption])
def list_pending_reservations(
    branch_id: str = Query(..., description="ID de la sucursal"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista las reservas activas en la sucursal que tienen pago pendiente para cobrar en caja."""
    return PaymentService.get_pending_reservations_for_branch(
        db=db,
        user=current_user,
        branch_id=branch_id,
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene el detalle de un cobro específico."""
    return PaymentService.get_payment(db=db, payment_id=payment_id, user=current_user)


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crea una nueva orden de cobro en caja (manual o vinculada a una reserva)."""
    return PaymentService.create_payment(db=db, user=current_user, data=payload)


@router.post("/{payment_id}/cash", response_model=PaymentResponse)
def process_cash_payment(
    payment_id: str,
    payload: Optional[PaymentProcess] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Registra el cobro inmediato en efectivo en la caja física.
    Si está asociado a una reserva, la completa y recién aquí genera
    el movimiento de salida en el inventario (CU09).
    """
    notes = payload.notes if payload else None
    return PaymentService.process_cash_payment(
        db=db,
        user=current_user,
        payment_id=payment_id,
        notes=notes,
    )


@router.post("/{payment_id}/paypal-order", response_model=PaymentPayPalOrderResponse)
def create_paypal_checkout(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Genera la orden y el enlace de checkout en PayPal Sandbox para cobrar en caja."""
    return PaymentService.create_paypal_checkout(
        db=db,
        user=current_user,
        payment_id=payment_id,
    )


@router.post("/{payment_id}/paypal-capture", response_model=PaymentResponse)
def capture_paypal_payment(
    payment_id: str,
    order_id: str = Query(..., description="ID de la orden de PayPal aprobada"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Captura los fondos desde PayPal Sandbox.
    Marca el cobro como PAGADO, completa la reserva vinculada y
    recién aquí genera el movimiento de salida en el inventario (CU09).
    """
    return PaymentService.capture_paypal_payment(
        db=db,
        user=current_user,
        payment_id=payment_id,
        paypal_order_id=order_id,
    )
