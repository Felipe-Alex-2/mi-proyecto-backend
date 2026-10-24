"""Authenticated, idempotent outbox commands; no arbitrary HTTP replay."""
import hashlib
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.base_datos import get_db
from app.api.dependencias import get_current_user
from app.modelos.usuario import Usuario
from app.modelos.carrito_item import CarritoItem
from app.modelos.operacion_sincronizacion import OperacionSincronizacion
from app.esquemas.carrito import CarritoItemAdd, CarritoItemUpdate
from app.esquemas.reserva import ReservaCreate, CapturaPayPalRequest
from app.esquemas.usuario import UsuarioUpdate, UsuarioResponse
from app.servicios.carrito_service import CarritoService
from app.servicios.reserva_service import ReservaService
from app.servicios.usuario_service import UsuarioService
from app.esquemas.vestidor_virtual import PerfilBiometricoCreate, PerfilBiometricoResponse
from app.servicios.vestidor_virtual_service import VestidorVirtualService
from app.servicios.notificacion_service import NotificacionService

router = APIRouter(prefix="/sync", tags=["Offline synchronization"])


@router.get('/status')
def sync_status():
    """Lightweight reachability probe; no tenant or account information."""
    return {'online': True}


class ComandoSincronizacion(BaseModel):
    operation_id: uuid.UUID
    account_id: str | None = Field(default=None, max_length=36)
    tenant_id: str | None = Field(default=None, max_length=36)
    branch_id: str | None = Field(default=None, max_length=36)
    method: str = Field(pattern="^(POST|PUT|DELETE|PATCH)$")
    path: str = Field(max_length=200)
    body: dict = Field(default_factory=dict)


def dispatch(db, user, command):
    path, method, body = command.path, command.method, command.body.copy()
    if path == '/payments/offline-sale' and method == 'POST':
        from app.esquemas.pago import PagoCreate
        from app.servicios.pago_service import PagoService
        from app.modelos.stock import Stock
        from app.modelos.variante_producto import VarianteProducto
        from app.nucleo.ambito_sucursal import resolve_branch
        from decimal import Decimal
        data = PagoCreate.model_validate(body)
        resolve_branch(user, data.branch_id)
        if data.payment_type != 'EFECTIVO':
            raise HTTPException(422, 'Los cobros offline deben ser en efectivo.')
        if data.reservation_id:
            from app.modelos.reserva import Reserva
            from app.servicios.saas_service import aware, utcnow
            reservation = db.query(Reserva).filter(Reserva.id==data.reservation_id,
                Reserva.branch_id==data.branch_id).with_for_update().first()
            if not reservation or reservation.status not in ('PENDING','CONFIRMED') or reservation.payment_status=='PAID' or not reservation.expires_at or aware(reservation.expires_at)<=utcnow():
                raise HTTPException(409, 'La reserva ya no admite este cobro. Revisa su estado.')
            if data.items:
                raise HTTPException(422, 'Un cobro de reserva no puede contener otra venta de prendas.')
            total = reservation.total_amount if reservation.total_amount is not None else sum(float(item.variant.product.price)*item.quantity for item in reservation.items if item.variant and item.variant.product)
            if Decimal(str(data.amount)).quantize(Decimal('.01')) != Decimal(str(total)).quantize(Decimal('.01')):
                raise HTTPException(409, 'El importe no coincide con la reserva.')
            payment = PagoService.create_payment(db, user, data)
            return PagoService.process_cash_payment(db, user, payment.id, data.notes)
        if not data.items:
            payment = PagoService.create_payment(db, user, data)
            return PagoService.process_cash_payment(db, user, payment.id, data.notes)
        ids = [item.variant_id for item in data.items]
        if len(set(ids)) != len(ids):
            raise HTTPException(422, 'Agrupa las cantidades de cada variante en una sola línea.')
        stocks = db.query(Stock).filter(Stock.branch_id == data.branch_id,
            Stock.variant_id.in_(ids)).order_by(Stock.variant_id).with_for_update().populate_existing().all()
        available = {stock.variant_id:stock.quantity for stock in stocks}
        for item in data.items:
            variant = db.query(VarianteProducto).filter(VarianteProducto.id == item.variant_id).first()
            if not variant or not variant.product or not variant.product.is_active:
                raise HTTPException(409, 'Una prenda ya no está disponible. Revisa la venta pendiente.')
            if available.get(item.variant_id, 0) < item.quantity:
                from app.nucleo.excepciones import insufficient_stock
                insufficient_stock(db, item.variant_id, variant.product.name, available.get(item.variant_id, 0), item.quantity)
            base_price = float(variant.price_override if variant.price_override is not None else variant.product.price)
            promotion = variant.product.promotion
            discount = float(promotion.discount_percent) if promotion and promotion.is_active and promotion.discount_percent else 0
            expected_price = round(base_price * (1 - discount / 100), 2)
            if Decimal(str(item.unit_price)).quantize(Decimal('.01')) != Decimal(str(expected_price)).quantize(Decimal('.01')):
                raise HTTPException(409, f'El precio de {variant.product.name} cambió. Revisa la venta con el cliente.')
        payment = PagoService.create_payment(db, user, data)
        return PagoService.process_cash_payment(db, user, payment.id, data.notes)
    if path == "/virtual-fitting/profile" and method == "POST":
        return PerfilBiometricoResponse.model_validate(VestidorVirtualService.upsert_profile(db,user.id,PerfilBiometricoCreate.model_validate(body)))
    if path == "/notifications/read-all" and method == "PATCH":
        return {"count":NotificacionService.mark_all_as_read(db,user)}
    if path.startswith("/notifications/") and path.endswith("/read") and method == "PATCH":
        result = NotificacionService.mark_as_read(db,user,path.split("/")[-2])
        return {"id":result.id,"is_read":True}
    if path == "/reservations/paypal-capture" and method == "POST":
        request = CapturaPayPalRequest.model_validate(body)
        return ReservaService.capture_paypal_order(db, user, request.paypal_order_id)
    if path == "/reservations" and method == "POST":
        # An offline PayPal intent reserves stock, but does not charge money.
        data = ReservaCreate.model_validate(body)
        return ReservaService.create_reservation(db, user, data)
    if path.startswith("/reservations/") and method == "DELETE":
        return ReservaService.cancel_by_customer(db, path.split("/")[-1], user)
    if path == "/cart/items" and method == "POST":
        return CarritoService.add_item(db, user.id, CarritoItemAdd.model_validate(body))
    if path == "/cart" and method == "DELETE":
        return CarritoService.clear_cart(db, user.id)
    if path.startswith("/cart/items/") and method in ("PUT", "DELETE"):
        variant_id = body.pop("_variant_id", None)
        item = db.query(CarritoItem).filter(CarritoItem.user_id == user.id)
        item = item.filter(CarritoItem.variant_id == variant_id) if variant_id else item.filter(CarritoItem.id == path.split("/")[-1])
        item = item.first()
        if not item:
            if method == "DELETE":
                return CarritoService.get_cart(db, user.id)
            raise HTTPException(409, "La prenda ya no está en tu carrito. Revisa los cambios pendientes.")
        if method == "PUT":
            return CarritoService.update_item_quantity(db, user.id, item.id, CarritoItemUpdate.model_validate(body))
        return CarritoService.remove_item(db, user.id, item.id)
    from app.servicios.administracion_sin_conexion_service import dispatch_admin
    return dispatch_admin(db, user, command)


@router.post("/operations")
def apply_operation(command: ComandoSincronizacion, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    if command.account_id is not None and command.account_id != user.id:
        raise HTTPException(403, "Esta operación pertenece a otra cuenta. Inicia sesión con su cuenta original.")
    serialized = command.model_dump(mode='json')
    for field in ('tenant_id', 'branch_id'):
        if serialized[field] is None:
            serialized.pop(field)  # Keep pre-SaaS operation fingerprints compatible.
    fingerprint = hashlib.sha256(json.dumps(serialized, sort_keys=True).encode()).hexdigest()
    # Serializes retries for one account across processes in PostgreSQL.
    db.query(Usuario).filter(Usuario.id == user.id).with_for_update().first()
    receipt = db.query(OperacionSincronizacion).filter_by(user_id=user.id, operation_id=str(command.operation_id)).first()
    if receipt:
        if receipt.fingerprint != fingerprint:
            legacy = {k:v for k,v in serialized.items() if k not in ('tenant_id', 'branch_id')}
            legacy_hash = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
            from app.modelos.saas import ROOT_TENANT_ID
            if command.tenant_id != ROOT_TENANT_ID or receipt.fingerprint != legacy_hash:
                raise HTTPException(409, "La misma operación no puede reutilizarse con otros datos.")
        return json.loads(receipt.response)
    db.info["sync_atomic"] = True
    try:
        from app.servicios.administracion_sin_conexion_service import resolve_command
        resolved_command = resolve_command(db, user, command)
        from app.modelos.sucursal import Sucursal
        from app.modelos.saas import ROOT_TENANT_ID
        from app.servicios.saas_service import enforce_subscription
        tenant_id = command.tenant_id or db.info.get('tenant_id') or (
            user.selected_tenant_id if user.role == 'CUSTOMER' else user.tenant_id) or ROOT_TENANT_ID
        branch_id = resolved_command.branch_id or resolved_command.body.get('branch_id')
        if user.role != 'CUSTOMER' and tenant_id != (user.tenant_id or db.info.get('tenant_id') or ROOT_TENANT_ID):
            raise HTTPException(403, 'Esta operación pertenece a otra empresa.')
        if branch_id:
            branch = db.query(Sucursal).execution_options(skip_tenant=True).filter(
                Sucursal.id == branch_id, Sucursal.tenant_id == tenant_id).first()
            if not branch:
                raise HTTPException(403, 'La sucursal no pertenece a la empresa original de la operación.')
        db.info.update(tenant_id=tenant_id, tenant_context=True, actor_id=user.id, personal_history=False,
                       customer_branch_id=branch_id if user.role == 'CUSTOMER' else None)
        if command.path not in ('/users/me', '/virtual-fitting/profile') and not command.path.startswith('/notifications/'):
            enforce_subscription(db, tenant_id, write=True)
        result = jsonable_encoder(dispatch(db, user, resolved_command))
        db.add(OperacionSincronizacion(id=str(uuid.uuid4()), user_id=user.id,
                             operation_id=str(command.operation_id), fingerprint=fingerprint,
                             response=json.dumps(result)))
        db.commit()
        return result
    except ValidationError as error:
        db.rollback()
        raise HTTPException(422, "Datos de la operación inválidos: " + str(error)) from error
    except OperationalError as error:
        db.rollback()
        raise HTTPException(503, "La operación está ocupada. Se reintentará con el mismo identificador.") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.info.pop("sync_atomic", None)
