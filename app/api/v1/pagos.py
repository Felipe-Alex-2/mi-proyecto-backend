from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.esquemas.pago import (
    PagoCreate,
    PagoResponse,
    OrdenPagoPayPalResponse,
    OpcionReservaPendiente,
    PagoProcess,
)
from app.servicios.pago_service import PagoService
from app.api.dependencias import get_current_user, get_current_user_flexible

router = APIRouter(prefix="/payments", tags=["Caja y Pagos (POS)"])


@router.get("", response_model=List[PagoResponse])
def list_payments(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrar por estado (PENDING, PAID, CANCELLED)"),
    payment_type: Optional[str] = Query(None, description="Filtrar por tipo (EFECTIVO, PAYPAL)"),
    search: Optional[str] = Query(None, description="Búsqueda por cliente, código o concepto"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista transacciones de caja e historial de cobros."""
    return PagoService.list_payments(
        db=db,
        user=current_user,
        branch_id=branch_id,
        status=status_filter,
        payment_type=payment_type,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/pending-reservations", response_model=List[OpcionReservaPendiente])
def list_pending_reservations(
    branch_id: str = Query(..., description="ID de la sucursal"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista las reservas activas en la sucursal que tienen pago pendiente para cobrar en caja."""
    return PagoService.get_pending_reservations_for_branch(
        db=db,
        user=current_user,
        branch_id=branch_id,
    )


@router.get("/{payment_id}", response_model=PagoResponse)
def get_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Obtiene el detalle de un cobro específico."""
    return PagoService.get_payment(db=db, payment_id=payment_id, user=current_user)


@router.post("", response_model=PagoResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PagoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Crea una nueva orden de cobro en caja (manual o vinculada a una reserva)."""
    return PagoService.create_payment(db=db, user=current_user, data=payload)


@router.post("/{payment_id}/cash", response_model=PagoResponse)
def process_cash_payment(
    payment_id: str,
    payload: Optional[PagoProcess] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Registra el cobro inmediato en efectivo en la caja física.
    Si está asociado a una reserva, la completa y recién aquí genera
    el movimiento de salida en el inventario (CU09).
    """
    notes = payload.notes if payload else None
    return PagoService.process_cash_payment(
        db=db,
        user=current_user,
        payment_id=payment_id,
        notes=notes,
    )


@router.post("/{payment_id}/paypal-order", response_model=OrdenPagoPayPalResponse)
def create_paypal_checkout(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Genera la orden y el enlace de checkout en PayPal Sandbox para cobrar en caja."""
    return PagoService.create_paypal_checkout(
        db=db,
        user=current_user,
        payment_id=payment_id,
    )


@router.post("/{payment_id}/paypal-capture", response_model=PagoResponse)
def capture_paypal_payment(
    payment_id: str,
    order_id: str = Query(..., description="ID de la orden de PayPal aprobada"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Captura los fondos desde PayPal Sandbox.
    Marca el cobro como PAGADO, completa la reserva vinculada y
    recién aquí genera el movimiento de salida en el inventario (CU09).
    """
    return PagoService.capture_paypal_payment(
        db=db,
        user=current_user,
        payment_id=payment_id,
        paypal_order_id=order_id,
    )


@router.post("/public-capture", response_model=PagoResponse)
def public_capture_paypal_order(
    order_id: str = Query(..., description="ID de la orden de PayPal"),
    db: Session = Depends(get_db),
):
    """
    Endpoint público para confirmar/capturar un cobro completado en PayPal Sandbox
    desde la página de retorno del navegador sin requerir sesión iniciada.
    """
    return PagoService.capture_paypal_by_order_id(db=db, paypal_order_id=order_id)


@router.get("/{payment_id}/invoice-pdf")
def get_payment_invoice_pdf(
    payment_id: str,
    token: Optional[str] = Query(None, description="Token JWT para descarga directa"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user_flexible),
):
    """
    Genera y descarga la factura oficial en formato PDF para una orden de cobro.
    """
    from fastapi import Response
    from app.servicios.factura_service import FacturaService
    from app.modelos.pago import Pago
    from app.nucleo.excepciones import NoEncontradoException

    payment = db.query(Pago).filter(Pago.id == payment_id).first()
    if not payment:
        raise NoEncontradoException(detail="Cobro no encontrado")
    from app.nucleo.ambito_sucursal import resolve_branch
    resolve_branch(current_user, payment.branch_id)

    pdf_bytes = FacturaService.generate_invoice_pdf(payment)
    filename = f"factura_{payment.payment_code}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "no-cache",
        },
    )

