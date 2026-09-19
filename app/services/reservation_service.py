import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.reservation import Reservation, ReservationStatus
from app.models.reservation_item import ReservationItem
from app.models.cart_item import CartItem
from app.models.branch import Branch
from app.models.product_variant import ProductVariant
from app.models.product import Product
from app.models.stock import Stock
from app.models.inventory_movement import InventoryMovement, MovementType
from app.models.user import User, UserRole
from app.schemas.reservation import (
    ReservationCreate,
    ReservationStatusUpdate,
    ReservationItemResponse,
    ReservationResponse,
    ReservationStatsResponse,
    PayPalReservationOrderCreate,
    PayPalOrderResponse,
    PayPalCaptureResponse,
)
from app.services.paypal_service import PayPalService
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
    ForbiddenException,
)


class ReservationService:
    @staticmethod
    def _enrich_reservation(r: Reservation) -> ReservationResponse:
        items_resp: List[ReservationItemResponse] = []
        total_items = 0
        total_estimated = 0.0

        for item in r.items:
            v = item.variant
            price = float(v.product.price) if (v and v.product and v.product.price is not None) else 0.0
            total_items += item.quantity
            total_estimated += price * item.quantity

            items_resp.append(
                ReservationItemResponse(
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
                    image_url=v.product.image_url if (v and v.product) else None,
                )
            )

        resp = ReservationResponse(
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
        customer: User,
        data: ReservationCreate,
    ) -> ReservationResponse:
        # Check active reservations count
        active_count = (
            db.query(Reservation)
            .filter(
                Reservation.customer_id == customer.id,
                Reservation.status.in_([ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value]),
            )
            .count()
        )
        if active_count >= 3:
            raise BadRequestException(
                detail="Límite alcanzado: no puedes tener más de 3 reservas activas simultáneamente"
            )

        branch = db.query(Branch).filter(Branch.id == data.branch_id).first()
        if not branch:
            raise NotFoundException(detail="Sucursal no encontrada")
        if not branch.is_active:
            raise BadRequestException(detail="La sucursal seleccionada no está activa")

        if not data.items:
            raise BadRequestException(detail="Debes seleccionar al menos una prenda para la reserva")

        # Validate stock availability in branch for each item
        variant_ids_in_reservation = []
        for item_in in data.items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item_in.variant_id).first()
            if not variant:
                raise NotFoundException(detail=f"Variante {item_in.variant_id} no encontrada")
            if variant.product and not variant.product.is_active:
                raise BadRequestException(
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
                raise BadRequestException(
                    detail=f"En esta sucursal no hay stock de esta prenda ({prod_name})"
                )
            if available < item_in.quantity:
                raise BadRequestException(
                    detail=f"Esta sucursal no tiene stock suficiente para {prod_name}. Disponible: {available}, solicitado: {item_in.quantity}"
                )
            variant_ids_in_reservation.append(item_in.variant_id)

        # Generate unique reservation code
        code = f"RSV-{uuid.uuid4().hex[:6].upper()}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=48)

        # Calculate estimated total amount
        total_estimated = 0.0
        for item_in in data.items:
            v = db.query(ProductVariant).filter(ProductVariant.id == item_in.variant_id).first()
            if v and v.product and v.product.price:
                total_estimated += float(v.product.price) * item_in.quantity

        reservation = Reservation(
            reservation_code=code,
            customer_id=customer.id,
            branch_id=data.branch_id,
            status=ReservationStatus.PENDING.value,
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
                stock.quantity = max(0, stock.quantity - item_in.quantity)

            res_item = ReservationItem(
                reservation_id=reservation.id,
                variant_id=item_in.variant_id,
                quantity=item_in.quantity,
            )
            db.add(res_item)

        # Auto-remove reserved variants from customer's cart
        if variant_ids_in_reservation:
            db.query(CartItem).filter(
                CartItem.user_id == customer.id,
                CartItem.variant_id.in_(variant_ids_in_reservation),
            ).delete(synchronize_session=False)

        db.commit()
        db.refresh(reservation)

        return cls._enrich_reservation(reservation)

    @classmethod
    def create_paypal_order(
        cls,
        db: Session,
        customer: User,
        data: PayPalReservationOrderCreate,
    ) -> PayPalOrderResponse:
        # Check active reservations count
        active_count = (
            db.query(Reservation)
            .filter(
                Reservation.customer_id == customer.id,
                Reservation.status.in_([ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value]),
            )
            .count()
        )
        if active_count >= 5:
            raise BadRequestException(
                detail="Límite alcanzado: no puedes tener más de 5 reservas activas simultáneamente"
            )

        branch = db.query(Branch).filter(Branch.id == data.branch_id).first()
        if not branch:
            raise NotFoundException(detail="Sucursal no encontrada")
        if not branch.is_active:
            raise BadRequestException(detail="La sucursal seleccionada no está activa")

        if not data.items:
            raise BadRequestException(detail="Debes seleccionar al menos una prenda para la reserva")

        # Validate stock availability in branch and calculate total amount
        total_amount = 0.0
        variant_ids_in_reservation = []
        for item_in in data.items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item_in.variant_id).first()
            if not variant:
                raise NotFoundException(detail=f"Variante {item_in.variant_id} no encontrada")
            if variant.product and not variant.product.is_active:
                raise BadRequestException(
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
                raise BadRequestException(
                    detail=f"En esta sucursal no hay stock de esta prenda ({prod_name})"
                )
            if available < item_in.quantity:
                raise BadRequestException(
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

        reservation = Reservation(
            reservation_code=code,
            customer_id=customer.id,
            branch_id=data.branch_id,
            status=ReservationStatus.PENDING.value,
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
                stock.quantity = max(0, stock.quantity - item_in.quantity)

            res_item = ReservationItem(
                reservation_id=reservation.id,
                variant_id=item_in.variant_id,
                quantity=item_in.quantity,
            )
            db.add(res_item)

        if variant_ids_in_reservation:
            db.query(CartItem).filter(
                CartItem.user_id == customer.id,
                CartItem.variant_id.in_(variant_ids_in_reservation),
            ).delete(synchronize_session=False)

        db.commit()
        db.refresh(reservation)

        return PayPalOrderResponse(
            order_id=paypal_order_id,
            approval_url=approval_url,
            reservation=cls._enrich_reservation(reservation),
        )

    @classmethod
    def capture_paypal_order(
        cls,
        db: Session,
        user: User,
        paypal_order_id: str,
    ) -> PayPalCaptureResponse:
        r = db.query(Reservation).filter(Reservation.paypal_order_id == paypal_order_id).first()
        if not r:
            raise NotFoundException(detail="No se encontró ninguna reserva asociada a esta orden de PayPal")

        # Idempotent check: if already PAID, return immediately
        if r.payment_status == "PAID":
            return PayPalCaptureResponse(
                order_id=paypal_order_id,
                capture_id=r.paypal_capture_id,
                status="COMPLETED",
                reservation=cls._enrich_reservation(r),
            )

        # Call PayPal REST API to capture funds
        capture_data = PayPalService.capture_order(paypal_order_id)
        capture_status = capture_data.get("status", "UNKNOWN")
        capture_id = capture_data.get("capture_id")

        if capture_status in ("COMPLETED", "APPROVED"):
            r.payment_status = "PAID"
            r.status = ReservationStatus.CONFIRMED.value
            r.paypal_capture_id = capture_id
            r.paid_at = datetime.now(timezone.utc)

            # Auto-register EXIT movement in inventory for confirmed and paid reservation
            for item in r.items:
                existing_exit = (
                    db.query(InventoryMovement)
                    .filter(
                        InventoryMovement.reference_number == r.reservation_code,
                        InventoryMovement.variant_id == item.variant_id,
                        InventoryMovement.type == MovementType.EXIT.value,
                    )
                    .first()
                )
                if not existing_exit:
                    stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).first()
                    curr_qty = stk.quantity if stk else 0
                    v = item.variant
                    item_price = float(v.product.price) if (v and v.product and v.product.price) else 0.0
                    mov = InventoryMovement(
                        variant_id=item.variant_id,
                        branch_id=r.branch_id,
                        type=MovementType.EXIT.value,
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

            db.commit()
            db.refresh(r)

        return PayPalCaptureResponse(
            order_id=paypal_order_id,
            capture_id=capture_id,
            status=capture_status,
            reservation=cls._enrich_reservation(r),
        )

    @classmethod
    def list_reservations(
        cls,
        db: Session,
        user: User,
        branch_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReservationResponse]:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        query = db.query(Reservation)

        if user_role == UserRole.CUSTOMER.value:
            query = query.filter(Reservation.customer_id == user.id)
        elif user_role in (UserRole.STORE_MANAGER.value, UserRole.CASHIER.value):
            if user.branch_id:
                query = query.filter(Reservation.branch_id == user.branch_id)
        else:  # ADMIN
            if branch_id:
                query = query.filter(Reservation.branch_id == branch_id)

        if status:
            query = query.filter(Reservation.status == status)

        reservations = query.order_by(Reservation.created_at.desc()).offset(offset).limit(limit).all()
        return [cls._enrich_reservation(r) for r in reservations]

    @classmethod
    def get_reservation(
        cls,
        db: Session,
        reservation_id: str,
        user: User,
    ) -> ReservationResponse:
        r = db.query(Reservation).filter(Reservation.id == reservation_id).first()
        if not r:
            raise NotFoundException(detail="Reserva no encontrada")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == UserRole.CUSTOMER.value and r.customer_id != user.id:
            raise ForbiddenException(detail="No tienes permiso para ver esta reserva")
        if user_role in (UserRole.STORE_MANAGER.value, UserRole.CASHIER.value) and r.branch_id != user.branch_id:
            raise ForbiddenException(detail="No tienes permiso para ver reservas de otra sucursal")

        return cls._enrich_reservation(r)

    @classmethod
    def update_status(
        cls,
        db: Session,
        reservation_id: str,
        user: User,
        data: ReservationStatusUpdate,
    ) -> ReservationResponse:
        r = db.query(Reservation).filter(Reservation.id == reservation_id).first()
        if not r:
            raise NotFoundException(detail="Reserva no encontrada")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role in (UserRole.STORE_MANAGER.value, UserRole.CASHIER.value):
            if r.branch_id != user.branch_id:
                raise ForbiddenException(detail="Solo puedes gestionar reservas de tu sucursal asignada")

        target_status = data.status.value if hasattr(data.status, "value") else str(data.status)
        notes = data.staff_notes.strip() if data.staff_notes else ""

        if target_status in (ReservationStatus.COMPLETED.value, ReservationStatus.CANCELLED.value):
            if len(notes) < 5:
                raise BadRequestException(
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
        if target_status in (ReservationStatus.CONFIRMED.value, ReservationStatus.COMPLETED.value):
            for item in r.items:
                v = item.variant
                item_price = float(v.product.price) if (v and v.product and v.product.price) else 0.0
                item_amount = round(item_price * item.quantity, 2)

                existing_exit = (
                    db.query(InventoryMovement)
                    .filter(
                        InventoryMovement.reference_number == r.reservation_code,
                        InventoryMovement.variant_id == item.variant_id,
                        InventoryMovement.type == MovementType.EXIT.value,
                    )
                    .first()
                )
                if not existing_exit:
                    stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).first()
                    curr_qty = stk.quantity if stk else 0
                    mov = InventoryMovement(
                        variant_id=item.variant_id,
                        branch_id=r.branch_id,
                        type=MovementType.EXIT.value,
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

        # If cancelling or expiring an active reservation, restore stock and log RETURN movement if previously confirmed
        if target_status in (ReservationStatus.CANCELLED.value, ReservationStatus.EXPIRED.value) and prev_status in (ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value):
            for item in r.items:
                stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).first()
                prev_qty = stk.quantity if stk else 0
                if stk:
                    stk.quantity += item.quantity
                new_qty = stk.quantity if stk else (prev_qty + item.quantity)

                had_exit = (
                    db.query(InventoryMovement)
                    .filter(
                        InventoryMovement.reference_number == r.reservation_code,
                        InventoryMovement.variant_id == item.variant_id,
                        InventoryMovement.type == MovementType.EXIT.value,
                    )
                    .first()
                )
                if had_exit:
                    return_mov = InventoryMovement(
                        variant_id=item.variant_id,
                        branch_id=r.branch_id,
                        type=MovementType.RETURN.value,
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
        db.commit()
        db.refresh(r)

        return cls._enrich_reservation(r)

    @classmethod
    def cancel_by_customer(
        cls,
        db: Session,
        reservation_id: str,
        customer: User,
    ) -> ReservationResponse:
        r = db.query(Reservation).filter(Reservation.id == reservation_id).first()
        if not r:
            raise NotFoundException(detail="Reserva no encontrada")

        if r.customer_id != customer.id:
            raise ForbiddenException(detail="No puedes cancelar una reserva de otro cliente")

        if r.status not in (ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value):
            raise BadRequestException(
                detail=f"No se puede cancelar una reserva que se encuentra en estado '{r.status}'"
            )

        for item in r.items:
            stk = db.query(Stock).filter(Stock.variant_id == item.variant_id, Stock.branch_id == r.branch_id).first()
            prev_qty = stk.quantity if stk else 0
            if stk:
                stk.quantity += item.quantity
            new_qty = stk.quantity if stk else (prev_qty + item.quantity)

            had_exit = (
                db.query(InventoryMovement)
                .filter(
                    InventoryMovement.reference_number == r.reservation_code,
                    InventoryMovement.variant_id == item.variant_id,
                    InventoryMovement.type == MovementType.EXIT.value,
                )
                .first()
            )
            if had_exit:
                return_mov = InventoryMovement(
                    variant_id=item.variant_id,
                    branch_id=r.branch_id,
                    type=MovementType.RETURN.value,
                    quantity=item.quantity,
                    reason=f"Devolución por cancelación de cliente ({r.reservation_code})",
                    reference_number=r.reservation_code,
                    previous_stock=prev_qty,
                    new_stock=new_qty,
                    user_id=customer.id,
                )
                db.add(return_mov)

        r.status = ReservationStatus.CANCELLED.value
        r.staff_notes = "Cancelada voluntariamente por el cliente desde la app"
        db.commit()
        db.refresh(r)

        return cls._enrich_reservation(r)

    @classmethod
    def get_stats(
        cls,
        db: Session,
        user: User,
        branch_id: Optional[str] = None,
    ) -> ReservationStatsResponse:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        query = db.query(Reservation)

        if user_role == UserRole.STORE_MANAGER.value:
            query = query.filter(Reservation.branch_id == user.branch_id)
        elif branch_id:
            query = query.filter(Reservation.branch_id == branch_id)

        all_res = query.all()
        total = len(all_res)
        pending = sum(1 for r in all_res if r.status == ReservationStatus.PENDING.value)
        confirmed = sum(1 for r in all_res if r.status == ReservationStatus.CONFIRMED.value)
        completed = sum(1 for r in all_res if r.status == ReservationStatus.COMPLETED.value)
        cancelled = sum(1 for r in all_res if r.status == ReservationStatus.CANCELLED.value)
        expired = sum(1 for r in all_res if r.status == ReservationStatus.EXPIRED.value)

        conversion_rate = round((completed / total * 100.0), 1) if total > 0 else 0.0

        return ReservationStatsResponse(
            total=total,
            pending=pending,
            confirmed=confirmed,
            completed=completed,
            cancelled=cancelled,
            expired=expired,
            conversion_rate=conversion_rate,
        )
