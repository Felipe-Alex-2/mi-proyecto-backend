from app.nucleo.transacciones import commit_or_flush
import uuid
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import update

logger = logging.getLogger("reservations")
from app.modelos.reserva import Reserva, EstadoReserva
from app.modelos.reserva_item import ReservaItem
from app.modelos.carrito_item import CarritoItem
from app.modelos.sucursal import Sucursal
from app.modelos.variante_producto import VarianteProducto
from app.modelos.producto import Producto
from app.modelos.stock import Stock
from app.modelos.movimiento_inventario import MovimientoInventario, TipoMovimiento
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.reserva import (
    ReservaCreate,
    EstadoReservaUpdate,
    ReservaItemResponse,
    ReservaResponse,
    EstadisticasReservaResponse,
    OrdenReservaPayPalCreate,
    OrdenPayPalResponse,
    CapturaPayPalResponse,
)
from app.servicios.paypal_service import PayPalService
from app.servicios.bitacora_service import BitacoraService
from app.nucleo.ambito_sucursal import resolve_branch
from app.nucleo.excepciones import (
    SolicitudInvalidaException,
    NoEncontradoException,
    AccesoDenegadoException,
    insufficient_stock,
)


class ReservaService:
    @staticmethod
    def _lock_allocation(db, customer_id, data):
        db.query(Usuario).filter(Usuario.id == customer_id).with_for_update().first()
        ids = sorted({item.variant_id for item in data.items})
        if len(ids) != len(data.items):
            raise SolicitudInvalidaException(detail="No repitas una variante en la misma reserva")
        db.query(Stock).filter(Stock.branch_id == data.branch_id, Stock.variant_id.in_(ids)).order_by(Stock.variant_id).with_for_update().populate_existing().all()

    @staticmethod
    def _enrich_reservation(r: Reserva) -> ReservaResponse:
        items_resp: List[ReservaItemResponse] = []
        total_items = 0
        total_estimated = 0.0

        for item in r.items:
            v = item.variant
            orig_price = float(v.product.price) if (v and v.product and v.product.price is not None) else 0.0
            discount_percent = (
                float(v.product.promotion.discount_percent)
                if (v and v.product and v.product.promotion and v.product.promotion.is_active and v.product.promotion.discount_percent)
                else None
            )
            if discount_percent and discount_percent > 0:
                price = round(orig_price * (1.0 - (discount_percent / 100.0)), 2)
            else:
                price = orig_price

            total_items += item.quantity
            total_estimated += price * item.quantity

            items_resp.append(
                ReservaItemResponse(
                    id=item.id,
                    variant_id=item.variant_id,
                    quantity=item.quantity,
                    product_id=v.product_id if v else None,
                    product_name=v.product.name if (v and v.product) else None,
                    sku=v.sku if v else None,
                    size_name=v.size.name if (v and v.size) else None,
                    color_name=v.color.name if (v and v.color) else None,
                    color_hex=v.color.hex_code if (v and v.color) else None,
                    price=price,
                    original_price=orig_price if (discount_percent and discount_percent > 0) else None,
                    discount_percent=discount_percent,
                    image_url=v.product.image_url if (v and v.product) else None,
                )
            )

        resp = ReservaResponse(
            tenant_id=r.tenant_id,
            company_name=r.company.name if r.company else None,
            id=r.id,
            reservation_code=r.reservation_code,
            customer_id=r.customer_id,
            branch_id=r.branch_id,
            status=r.status,
            customer_notes=r.customer_notes,
            staff_notes=r.staff_notes,
            staff_user_id=r.staff_user_id,
            created_at=r.created_at,
            expires_at=r.expires_at,
            updated_at=r.updated_at,
            payment_method=r.payment_method or "EFECTIVO",
            payment_status=r.payment_status or "PENDING",
            paypal_order_id=r.paypal_order_id,
            paypal_capture_id=r.paypal_capture_id,
            paid_at=r.paid_at,
            total_amount=float(r.total_amount) if r.total_amount is not None else round(total_estimated, 2),
            items=items_resp,
            customer_name=r.customer.full_name if r.customer else None,
            customer_email=r.customer.email if r.customer else None,
            customer_phone=r.customer.phone if r.customer else None,
            branch_name=r.branch.name if r.branch else None,
            branch_address=r.branch.address if r.branch else None,
            total_items=total_items,
            total_estimated_amount=round(total_estimated, 2),
        )
        return resp

    @classmethod
    def create_reservation(
        cls,
        db: Session,
        customer: Usuario,
        data: ReservaCreate,
    ) -> ReservaResponse:
        if db.info.get('customer_branch_id') and data.branch_id != db.info['customer_branch_id']:
            raise SolicitudInvalidaException(detail='La reserva debe pertenecer a tu sucursal seleccionada.')
        cls._lock_allocation(db, customer.id, data)
        # Check active reservations count
        active_count = (
            db.query(Reserva)
            .filter(
                Reserva.customer_id == customer.id,
                Reserva.status.in_([EstadoReserva.PENDING.value, EstadoReserva.CONFIRMED.value]),
            )
            .count()
        )
        if active_count >= 3:
            raise SolicitudInvalidaException(
                detail="Límite alcanzado: no puedes tener más de 3 reservas activas simultáneamente"
            )

        branch = db.query(Sucursal).filter(Sucursal.id == data.branch_id).first()
        if not branch:
            raise NoEncontradoException(detail="Sucursal no encontrada")
        if not branch.is_active:
            raise SolicitudInvalidaException(detail="La sucursal seleccionada no está activa")

        if not data.items:
            raise SolicitudInvalidaException(detail="Debes seleccionar al menos una prenda para la reserva")

        # Validate stock availability in branch for each item
        variant_ids_in_reservation = []
        for item_in in data.items:
            variant = db.query(VarianteProducto).filter(VarianteProducto.id == item_in.variant_id).first()
            if not variant:
                raise NoEncontradoException(detail=f"Variante {item_in.variant_id} no encontrada")
            if variant.product and not variant.product.is_active:
                raise SolicitudInvalidaException(
                    detail=f"El producto '{variant.product.name}' no está disponible actualmente"
                )

            stock = (
                db.query(Stock)
                .filter(Stock.variant_id == item_in.variant_id, Stock.branch_id == data.branch_id)
                .first()
            )
            available = stock.quantity if stock else 0
            prod_name = variant.product.name if variant.product else "esta prenda"
            if available < item_in.quantity:
                insufficient_stock(db, item_in.variant_id, prod_name, available, item_in.quantity)
            variant_ids_in_reservation.append(item_in.variant_id)

        # Generate unique reservation code
        code = f"RSV-{uuid.uuid4().hex[:6].upper()}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=48)

        # Calculate estimated total amount with active promotion discounts
        total_estimated = 0.0
        for item_in in data.items:
            v = db.query(VarianteProducto).filter(VarianteProducto.id == item_in.variant_id).first()
            if v and v.product and v.product.price is not None:
                p = v.product
                orig_price = float(p.price)
                if p.promotion and p.promotion.is_active and p.promotion.discount_percent:
                    eff_price = round(orig_price * (1.0 - float(p.promotion.discount_percent) / 100.0), 2)
                else:
                    eff_price = orig_price
                total_estimated += eff_price * item_in.quantity

        reservation = Reserva(
            reservation_code=code,
            customer_id=customer.id,
            branch_id=data.branch_id,
            status=EstadoReserva.PENDING.value,
            customer_notes=data.customer_notes.strip() if data.customer_notes else None,
            payment_method=data.payment_method or "EFECTIVO",
            payment_status="PENDING",
            total_amount=round(total_estimated, 2),
            created_at=now,
            expires_at=expires_at,
        )
        db.add(reservation)
        db.flush()

        for item_in in data.items:
            stock = (
                db.query(Stock)
                .filter(Stock.variant_id == item_in.variant_id, Stock.branch_id == data.branch_id)
                .first()
            )
            if stock:
                changed = db.execute(update(Stock).where(
                    Stock.id == stock.id, Stock.quantity >= item_in.quantity
                ).values(quantity=Stock.quantity - item_in.quantity).execution_options(synchronize_session=False)).rowcount
                if changed != 1:
                    db.refresh(stock)
                    insufficient_stock(db, item_in.variant_id, "esta prenda", stock.quantity, item_in.quantity)
                db.expire(stock)

            res_item = ReservaItem(
                reservation_id=reservation.id,
                variant_id=item_in.variant_id,
                quantity=item_in.quantity,
            )
            db.add(res_item)

        # Auto-remove reserved variants from customer's cart
        if variant_ids_in_reservation:
            db.query(CarritoItem).filter(
                CarritoItem.user_id == customer.id,
                CarritoItem.variant_id.in_(variant_ids_in_reservation),
            ).delete(synchronize_session=False)

        commit_or_flush(db)
        db.refresh(reservation)

        BitacoraService.log_event(
            db=db,
            user=customer,
            action="CREAR_RESERVA",
            description=f"Reserva creada #{reservation.reservation_code} en sucursal {branch.name} por {len(data.items)} prenda(s)",
            category="RESERVAS",
            branch_id=reservation.branch_id,
        )

        return cls._enrich_reservation(reservation)

    @classmethod
    def create_paypal_order(
        cls,
        db: Session,
        customer: Usuario,
        data: OrdenReservaPayPalCreate,
    ) -> OrdenPayPalResponse:
        if db.info.get('customer_branch_id') and data.branch_id != db.info['customer_branch_id']:
            raise SolicitudInvalidaException(detail='La reserva debe pertenecer a tu sucursal seleccionada.')
        cls._lock_allocation(db, customer.id, data)
        # Check active reservations count
        active_count = (
            db.query(Reserva)
            .filter(
                Reserva.customer_id == customer.id,
                Reserva.status.in_([EstadoReserva.PENDING.value, EstadoReserva.CONFIRMED.value]),
            )
            .count()
        )
        if active_count >= 5:
            raise SolicitudInvalidaException(
                detail="Límite alcanzado: no puedes tener más de 5 reservas activas simultáneamente"
            )

        branch = db.query(Sucursal).filter(Sucursal.id == data.branch_id).first()
        if not branch:
            raise NoEncontradoException(detail="Sucursal no encontrada")
        if not branch.is_active:
            raise SolicitudInvalidaException(detail="La sucursal seleccionada no está activa")

        if not data.items:
            raise SolicitudInvalidaException(detail="Debes seleccionar al menos una prenda para la reserva")

        # Validate stock availability in branch and calculate total amount
        total_amount = 0.0
        variant_ids_in_reservation = []
        for item_in in data.items:
            variant = db.query(VarianteProducto).filter(VarianteProducto.id == item_in.variant_id).first()
            if not variant:
                raise NoEncontradoException(detail=f"Variante {item_in.variant_id} no encontrada")
            if variant.product and not variant.product.is_active:
                raise SolicitudInvalidaException(
                    detail=f"El producto '{variant.product.name}' no está disponible actualmente"
                )

            stock = (
                db.query(Stock)
                .filter(Stock.variant_id == item_in.variant_id, Stock.branch_id == data.branch_id)
                .first()
            )
            available = stock.quantity if stock else 0
            prod_name = variant.product.name if variant.product else "esta prenda"
            if available == 0:
                raise SolicitudInvalidaException(
                    detail=f"En esta sucursal no hay stock de esta prenda ({prod_name})"
                )
            if available < item_in.quantity:
                raise SolicitudInvalidaException(
                    detail=f"Esta sucursal no tiene stock suficiente para {prod_name}. Disponible: {available}, solicitado: {item_in.quantity}"
                )
            price = float(variant.product.price) if (variant.product and variant.product.price is not None) else 0.0
            total_amount += price * item_in.quantity
            variant_ids_in_reservation.append(item_in.variant_id)

        code = f"RSV-{uuid.uuid4().hex[:6].upper()}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=48)

        # Call PayPal REST API to create checkout order
        paypal_result = PayPalService.create_order(
            amount=total_amount,
            description=f"Pago de Reserva {code} en {branch.name}",
            return_url=data.return_url,
            cancel_url=data.cancel_url,
        )
        paypal_order_id = paypal_result["order_id"]
        approval_url = paypal_result["approval_url"]

        reservation = Reserva(
            reservation_code=code,
            customer_id=customer.id,
            branch_id=data.branch_id,
            status=EstadoReserva.PENDING.value,
            customer_notes=data.customer_notes.strip() if data.customer_notes else None,
            payment_method="PAYPAL",
            payment_status="PENDING",
            paypal_order_id=paypal_order_id,
            total_amount=round(total_amount, 2),
            created_at=now,
            expires_at=expires_at,
        )
        db.add(reservation)
        db.flush()

        for item_in in data.items:
            stock = (
                db.query(Stock)
                .filter(Stock.variant_id == item_in.variant_id, Stock.branch_id == data.branch_id)
                .first()
            )
            if stock:
                changed = db.execute(update(Stock).where(
                    Stock.id == stock.id, Stock.quantity >= item_in.quantity
                ).values(quantity=Stock.quantity - item_in.quantity).execution_options(synchronize_session=False)).rowcount
                if changed != 1:
                    raise SolicitudInvalidaException(detail="Otra reserva obtuvo primero estas prendas. Stock insuficiente.")
                db.expire(stock)

            res_item = ReservaItem(
                reservation_id=reservation.id,
                variant_id=item_in.variant_id,
                quantity=item_in.quantity,
            )
            db.add(res_item)

        if variant_ids_in_reservation:
            db.query(CarritoItem).filter(
                CarritoItem.user_id == customer.id,
                CarritoItem.variant_id.in_(variant_ids_in_reservation),
            ).delete(synchronize_session=False)

        commit_or_flush(db)
        db.refresh(reservation)

        BitacoraService.log_event(db, customer, "CREAR_RESERVA",
                                    f"Reserva #{reservation.reservation_code} creada con pago PayPal pendiente",
                                    "RESERVAS", branch_id=reservation.branch_id)
        return OrdenPayPalResponse(
            order_id=paypal_order_id,
            approval_url=approval_url,
            reservation=cls._enrich_reservation(reservation),
        )

    @classmethod
    def capture_paypal_order(
        cls,
        db: Session,
        user: Usuario,
        paypal_order_id: str,
    ) -> CapturaPayPalResponse:
        r = db.query(Reserva).filter(Reserva.paypal_order_id == paypal_order_id).with_for_update().first()
        if not r:
            raise NoEncontradoException(detail="No se encontró ninguna reserva asociada a esta orden de PayPal")

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if r.customer_id != user.id and role != RolUsuario.ADMIN.value:
            raise AccesoDenegadoException(detail="No puedes pagar la reserva de otro cliente")
        if r.status not in (EstadoReserva.PENDING.value, EstadoReserva.CONFIRMED.value):
            raise SolicitudInvalidaException(detail="Esta reserva ya no admite pagos")
        # Idempotent check: if already PAID, return immediately
        if r.payment_status == "PAID":
            return CapturaPayPalResponse(
                order_id=paypal_order_id,
                capture_id=r.paypal_capture_id,
                status="COMPLETED",
                reservation=cls._enrich_reservation(r),
            )

        expires = r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at
        if expires <= datetime.now(timezone.utc):
            raise SolicitudInvalidaException(detail="La reserva venció; revisa su disponibilidad antes de pagar")
        # Call PayPal REST API to capture funds
        capture_data = PayPalService.capture_order(paypal_order_id)
        capture_status = capture_data.get("status", "UNKNOWN")
        capture_id = capture_data.get("capture_id")

        if capture_status == "COMPLETED":
            r.payment_status = "PAID"
            r.status = EstadoReserva.CONFIRMED.value
            r.paypal_capture_id = capture_id
            r.paid_at = datetime.now(timezone.utc)

            # Auto-register EXIT movement in inventory for confirmed and paid reservation
            for item in r.items:
                existing_exit = (
                    db.query(MovimientoInventario)
                    .filter(
                        MovimientoInventario.reference_number == r.reservation_code,
                        MovimientoInventario.variant_id == item.variant_id,
                        MovimientoInventario.type == TipoMovimiento.EXIT.value,
                    )
                    .first()
                )
                if not existing_exit:
                    stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).with_for_update().populate_existing().first()
                    curr_qty = stk.quantity if stk else 0
                    v = item.variant
                    orig_p = float(v.product.price) if (v and v.product and v.product.price) else 0.0
                    if v and v.product and v.product.promotion and v.product.promotion.is_active and v.product.promotion.discount_percent:
                        item_price = round(orig_p * (1.0 - float(v.product.promotion.discount_percent) / 100.0), 2)
                    else:
                        item_price = orig_p
                    mov = MovimientoInventario(
                        variant_id=item.variant_id,
                        branch_id=r.branch_id,
                        type=TipoMovimiento.EXIT.value,
                        quantity=item.quantity,
                        reason=f"Venta pagada con PayPal por reserva ({r.reservation_code})",
                        reference_number=r.reservation_code,
                        previous_stock=curr_qty + item.quantity,
                        new_stock=curr_qty,
                        user_id=r.customer_id,
                        payment_method="PAYPAL",
                        payment_status="PAID",
                        amount=round(item_price * item.quantity, 2),
                        paypal_order_id=paypal_order_id,
                        paypal_capture_id=capture_id,
                    )
                    db.add(mov)

            commit_or_flush(db)
            db.refresh(r)

            BitacoraService.log_event(db, user, "COBRO_PAYPAL",
                                        f"Pago PayPal confirmado para reserva #{r.reservation_code}",
                                        "FINANZAS", branch_id=r.branch_id)

        return CapturaPayPalResponse(
            order_id=paypal_order_id,
            capture_id=capture_id,
            status=capture_status,
            reservation=cls._enrich_reservation(r),
        )

    @classmethod
    def list_reservations(
        cls,
        db: Session,
        user: Usuario,
        branch_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReservaResponse]:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        query = db.query(Reserva)

        if user_role == RolUsuario.CUSTOMER.value:
            query = query.filter(Reserva.customer_id == user.id)
        elif user_role in (RolUsuario.STORE_MANAGER.value, RolUsuario.CASHIER.value):
            query = query.filter(Reserva.branch_id == resolve_branch(user, branch_id))
        else:  # ADMIN
            if branch_id:
                query = query.filter(Reserva.branch_id == branch_id)

        if status:
            query = query.filter(Reserva.status == status)

        reservations = query.order_by(Reserva.created_at.desc()).offset(offset).limit(limit).all()
        return [cls._enrich_reservation(r) for r in reservations]

    @classmethod
    def get_reservation(
        cls,
        db: Session,
        reservation_id: str,
        user: Usuario,
    ) -> ReservaResponse:
        r = db.query(Reserva).filter(Reserva.id == reservation_id).with_for_update().first()
        if not r:
            raise NoEncontradoException(detail="Reserva no encontrada")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == RolUsuario.CUSTOMER.value and r.customer_id != user.id:
            raise AccesoDenegadoException(detail="No tienes permiso para ver esta reserva")
        if user_role in (RolUsuario.STORE_MANAGER.value, RolUsuario.CASHIER.value) and r.branch_id != user.branch_id:
            raise AccesoDenegadoException(detail="No tienes permiso para ver reservas de otra sucursal")

        return cls._enrich_reservation(r)

    @classmethod
    def update_status(
        cls,
        db: Session,
        reservation_id: str,
        user: Usuario,
        data: EstadoReservaUpdate,
    ) -> ReservaResponse:
        r = db.query(Reserva).filter(Reserva.id == reservation_id).with_for_update().first()
        if not r:
            raise NoEncontradoException(detail="Reserva no encontrada")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role in (RolUsuario.STORE_MANAGER.value, RolUsuario.CASHIER.value):
            if r.branch_id != user.branch_id:
                raise AccesoDenegadoException(detail="Solo puedes gestionar reservas de tu sucursal asignada")

        target_status = data.status.value if hasattr(data.status, "value") else str(data.status)
        notes = data.staff_notes.strip() if data.staff_notes else ""

        if target_status in (EstadoReserva.COMPLETED.value, EstadoReserva.CANCELLED.value):
            if len(notes) < 5:
                raise SolicitudInvalidaException(
                    detail="Se requiere una nota explicativa de al menos 5 caracteres al completar o cancelar una reserva"
                )

        prev_status = r.status

        # Update payment method and status if provided
        if data.payment_method:
            r.payment_method = data.payment_method
        if data.payment_status:
            r.payment_status = data.payment_status
            if data.payment_status == "PAID" and not r.paid_at:
                r.paid_at = datetime.now(timezone.utc)

        # If transitioning to CONFIRMED or COMPLETED, automatically register or update EXIT movements (sales/deductions)
        if target_status in (EstadoReserva.CONFIRMED.value, EstadoReserva.COMPLETED.value):
            for item in r.items:
                v = item.variant
                item_price = float(v.product.price) if (v and v.product and v.product.price) else 0.0
                item_amount = round(item_price * item.quantity, 2)

                existing_exit = (
                    db.query(MovimientoInventario)
                    .filter(
                        MovimientoInventario.reference_number == r.reservation_code,
                        MovimientoInventario.variant_id == item.variant_id,
                        MovimientoInventario.type == TipoMovimiento.EXIT.value,
                    )
                    .first()
                )
                if not existing_exit:
                    stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).with_for_update().populate_existing().first()
                    curr_qty = stk.quantity if stk else 0
                    mov = MovimientoInventario(
                        variant_id=item.variant_id,
                        branch_id=r.branch_id,
                        type=TipoMovimiento.EXIT.value,
                        quantity=item.quantity,
                        reason=f"Venta por reserva confirmada ({r.reservation_code})",
                        reference_number=r.reservation_code,
                        previous_stock=curr_qty + item.quantity,
                        new_stock=curr_qty,
                        user_id=user.id,
                        payment_method=r.payment_method or "EFECTIVO",
                        payment_status=r.payment_status or "PENDING",
                        amount=item_amount,
                        paypal_order_id=r.paypal_order_id,
                        paypal_capture_id=r.paypal_capture_id,
                    )
                    db.add(mov)
                else:
                    if r.payment_method:
                        existing_exit.payment_method = r.payment_method
                    if r.payment_status:
                        existing_exit.payment_status = r.payment_status
                    if not existing_exit.amount or existing_exit.amount == 0:
                        existing_exit.amount = item_amount

            # If COMPLETED and payment is still PENDING, also ensure a Pago order exists in payments table
            if target_status == EstadoReserva.COMPLETED.value and r.payment_status != "PAID":
                from app.modelos.pago import Pago
                existing_p = db.query(Pago).filter(Pago.reservation_id == r.id).first()
                if not existing_p:
                    customer_name = r.customer.full_name if r.customer else "Cliente General"
                    customer_email = r.customer.email if r.customer else None
                    token = secrets.token_hex(3).upper()
                    tot_items = sum(it.quantity for it in r.items)
                    new_p = Pago(
                        payment_code=f"PAY-{token}",
                        branch_id=r.branch_id,
                        reservation_id=r.id,
                        customer_id=r.customer_id,
                        customer_name=customer_name,
                        customer_email=customer_email,
                        concept=f"Reserva {r.reservation_code} ({tot_items} prendas)",
                        amount=float(r.total_amount or r.total_estimated_amount),
                        currency="USD",
                        payment_type=r.payment_method or "EFECTIVO",
                        status="PENDING",
                        reference="Pendiente en Caja",
                        cashier_id=user.id,
                        notes=f"Enviada a caja desde Reservas. {notes}".strip(),
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(new_p)

        # If cancelling or expiring an active reservation, restore stock and log RETURN movement if previously confirmed
        if target_status in (EstadoReserva.CANCELLED.value, EstadoReserva.EXPIRED.value) and prev_status in (EstadoReserva.PENDING.value, EstadoReserva.CONFIRMED.value):
            for item in r.items:
                stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).with_for_update().populate_existing().first()
                prev_qty = stk.quantity if stk else 0
                if stk:
                    stk.quantity += item.quantity
                new_qty = stk.quantity if stk else (prev_qty + item.quantity)

                had_exit = (
                    db.query(MovimientoInventario)
                    .filter(
                        MovimientoInventario.reference_number == r.reservation_code,
                        MovimientoInventario.variant_id == item.variant_id,
                        MovimientoInventario.type == TipoMovimiento.EXIT.value,
                    )
                    .first()
                )
                if had_exit:
                    return_mov = MovimientoInventario(
                        variant_id=item.variant_id,
                        branch_id=r.branch_id,
                        type=TipoMovimiento.RETURN.value,
                        quantity=item.quantity,
                        reason=f"Devolución por reserva cancelada ({r.reservation_code})",
                        reference_number=r.reservation_code,
                        previous_stock=prev_qty,
                        new_stock=new_qty,
                        user_id=user.id,
                    )
                    db.add(return_mov)

        r.status = target_status
        r.staff_notes = notes if notes else None
        r.staff_user_id = user.id
        commit_or_flush(db)
        db.refresh(r)

        BitacoraService.log_event(
            db=db,
            user=user,
            action="ACTUALIZAR_ESTADO_RESERVA",
            description=f"Reserva #{r.reservation_code} cambiada de {prev_status} a {target_status}",
            category="RESERVAS",
            branch_id=r.branch_id,
        )

        # Trigger customer notification when reservation is accepted/confirmed
        if target_status == EstadoReserva.CONFIRMED.value:
            from app.servicios.notificacion_service import NotificacionService
            try:
                NotificacionService.create_reservation_accepted_notification(db, r)
            except Exception as notif_err:
                logger.warning(f"Error creando notificación para reserva {r.id}: {notif_err}")

        return cls._enrich_reservation(r)

    @classmethod
    def cancel_by_customer(
        cls,
        db: Session,
        reservation_id: str,
        customer: Usuario,
    ) -> ReservaResponse:
        query = db.query(Reserva)
        if customer.role == 'CUSTOMER':
            query = query.execution_options(skip_tenant=True).filter(Reserva.customer_id == customer.id)
        r = query.filter(Reserva.id == reservation_id).with_for_update().first()
        if not r:
            raise NoEncontradoException(detail="Reserva no encontrada")

        if r.customer_id != customer.id:
            raise AccesoDenegadoException(detail="No puedes cancelar una reserva de otro cliente")
        db.info.update(tenant_id=r.tenant_id, customer_branch_id=r.branch_id, personal_history=False)
        if r.payment_status == "PAID":
            raise SolicitudInvalidaException(detail="Esta reserva está pagada. Solicita su cancelación y reembolso en la sucursal.")

        if r.status not in (EstadoReserva.PENDING.value, EstadoReserva.CONFIRMED.value):
            raise SolicitudInvalidaException(
                detail=f"No se puede cancelar una reserva que se encuentra en estado '{r.status}'"
            )

        for item in r.items:
            stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).with_for_update().populate_existing().first()
            prev_qty = stk.quantity if stk else 0
            if stk:
                stk.quantity += item.quantity
            new_qty = stk.quantity if stk else (prev_qty + item.quantity)

            had_exit = (
                db.query(MovimientoInventario)
                .filter(
                    MovimientoInventario.reference_number == r.reservation_code,
                    MovimientoInventario.variant_id == item.variant_id,
                    MovimientoInventario.type == TipoMovimiento.EXIT.value,
                )
                .first()
            )
            if had_exit:
                return_mov = MovimientoInventario(
                    variant_id=item.variant_id,
                    branch_id=r.branch_id,
                    type=TipoMovimiento.RETURN.value,
                    quantity=item.quantity,
                    reason=f"Devolución por cancelación de cliente ({r.reservation_code})",
                    reference_number=r.reservation_code,
                    previous_stock=prev_qty,
                    new_stock=new_qty,
                    user_id=customer.id,
                )
                db.add(return_mov)

        r.status = EstadoReserva.CANCELLED.value
        r.staff_notes = "Cancelada voluntariamente por el cliente desde la app"
        commit_or_flush(db)
        db.refresh(r)

        BitacoraService.log_event(
            db=db,
            user=customer,
            action="CANCELAR_RESERVA",
            description=f"Cliente canceló reserva #{r.reservation_code}",
            category="RESERVAS",
            branch_id=r.branch_id,
        )

        return cls._enrich_reservation(r)

    @classmethod
    def get_stats(
        cls,
        db: Session,
        user: Usuario,
        branch_id: Optional[str] = None,
    ) -> EstadisticasReservaResponse:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        query = db.query(Reserva)

        if user_role in (RolUsuario.STORE_MANAGER.value, RolUsuario.CASHIER.value):
            query = query.filter(Reserva.branch_id == resolve_branch(user, branch_id))
        elif branch_id:
            query = query.filter(Reserva.branch_id == branch_id)

        all_res = query.all()
        total = len(all_res)
        pending = sum(1 for r in all_res if r.status == EstadoReserva.PENDING.value)
        confirmed = sum(1 for r in all_res if r.status == EstadoReserva.CONFIRMED.value)
        completed = sum(1 for r in all_res if r.status == EstadoReserva.COMPLETED.value)
        cancelled = sum(1 for r in all_res if r.status == EstadoReserva.CANCELLED.value)
        expired = sum(1 for r in all_res if r.status == EstadoReserva.EXPIRED.value)

        conversion_rate = round((completed / total * 100.0), 1) if total > 0 else 0.0

        return EstadisticasReservaResponse(
            total=total,
            pending=pending,
            confirmed=confirmed,
            completed=completed,
            cancelled=cancelled,
            expired=expired,
            conversion_rate=conversion_rate,
        )
