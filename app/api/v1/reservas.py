from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.dependencias import get_current_user, require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.reserva import (
    ReservaCreate,
    EstadoReservaUpdate,
    ReservaResponse,
    EstadisticasReservaResponse,
    OrdenReservaPayPalCreate,
    OrdenPayPalResponse,
    CapturaPayPalRequest,
    CapturaPayPalResponse,
)
from app.servicios.reserva_service import ReservaService

router = APIRouter(prefix="/reservations", tags=["In-Store Try-On Reservations (CU13)"])


@router.post("/{id}/paypal-order", response_model=OrdenPayPalResponse)
def pay_existing_reservation(id: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Resume an offline payment intent without creating another reservation."""
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from app.modelos.reserva import Reserva
    from app.servicios.paypal_service import PayPalService
    r = db.query(Reserva).filter(Reserva.id == id).with_for_update().first()
    if not r or r.customer_id != current_user.id:
        raise HTTPException(404, "Reserva no encontrada")
    expires = r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at
    if r.status not in ("PENDING", "CONFIRMED") or r.payment_status == "PAID" or expires <= datetime.now(timezone.utc):
        raise HTTPException(409, "Esta reserva ya no admite pagos")
    if r.paypal_order_id:
        order = PayPalService.get_order(r.paypal_order_id)
        approval = next((link['href'] for link in order.get('links', []) if link.get('rel') in ('approve','payer-action')), None)
        if not approval:
            raise HTTPException(409, "La orden ya fue aprobada o necesita verificarse. Consulta el pago antes de continuar.")
        return {"order_id":r.paypal_order_id,"approval_url":approval,"reservation":ReservaService._enrich_reservation(r)}
    result = PayPalService.create_order(amount=float(r.total_amount), description=f"Reserva {r.reservation_code}", custom_id=r.id, request_id=r.id)
    r.paypal_order_id = result['order_id']
    r.payment_method = 'PAYPAL'
    db.commit()
    return {**result,"reservation":ReservaService._enrich_reservation(r)}


@router.post(
    "",
    response_model=ReservaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una nueva reserva para prueba presencial de prendas",
)
def create_reservation(
    payload: ReservaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ReservaService.create_reservation(db=db, customer=current_user, data=payload)


@router.post(
    "/paypal-order",
    response_model=OrdenPayPalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear orden en PayPal Sandbox para pagar y reservar prendas",
)
def create_paypal_reservation_order(
    payload: OrdenReservaPayPalCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ReservaService.create_paypal_order(db=db, customer=current_user, data=payload)


@router.post(
    "/paypal-capture",
    response_model=CapturaPayPalResponse,
    status_code=status.HTTP_200_OK,
    summary="Capturar y confirmar pago aprobado en PayPal",
)
def capture_paypal_reservation_order(
    payload: CapturaPayPalRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ReservaService.capture_paypal_order(
        db=db, user=current_user, paypal_order_id=payload.paypal_order_id
    )


@router.get(
    "",
    response_model=List[ReservaResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar reservas (Clientes ven las suyas; Encargado/Cajero ven su sucursal; Admin ve todas)",
)
def list_reservations(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal (solo Admin)"),
    status: Optional[str] = Query(None, description="Filtrar por estado"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ReservaService.list_reservations(
        db=db,
        user=current_user,
        branch_id=branch_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats",
    response_model=EstadisticasReservaResponse,
    status_code=status.HTTP_200_OK,
    summary="Estadísticas generales de reservas y conversión (Admin / Encargado)",
)
def get_reservation_stats(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER, RolUsuario.CASHIER)),
):
    return ReservaService.get_stats(db=db, user=current_user, branch_id=branch_id)


@router.get(
    "/{id}",
    response_model=ReservaResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle completo de una reserva",
)
def get_reservation(
    id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ReservaService.get_reservation(db=db, reservation_id=id, user=current_user)


@router.patch(
    "/{id}/status",
    response_model=ReservaResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar estado de la reserva (Staff)",
)
def update_reservation_status(
    id: str,
    payload: EstadoReservaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER, RolUsuario.CASHIER)),
):
    return ReservaService.update_status(db=db, reservation_id=id, user=current_user, data=payload)


@router.delete(
    "/{id}",
    response_model=ReservaResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancelar una reserva propia (Cliente)",
)
def cancel_reservation(
    id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ReservaService.cancel_by_customer(db=db, reservation_id=id, customer=current_user)
