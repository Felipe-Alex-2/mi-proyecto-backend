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
from app.models.user import User, UserRole
from app.schemas.reservation import (
    ReservationCreate,
    ReservationStatusUpdate,
    ReservationItemResponse,
    ReservationResponse,
    ReservationStatsResponse,
)
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
            if available < item_in.quantity:
                prod_name = variant.product.name if variant.product else "Prenda"
                raise BadRequestException(
                    detail=f"Stock insuficiente en '{branch.name}' para '{prod_name}'. Disponible: {available}, solicitado: {item_in.quantity}"
                )
            variant_ids_in_reservation.append(item_in.variant_id)

        # Generate unique reservation code
        code = f"RSV-{uuid.uuid4().hex[:6].upper()}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=48)

        reservation = Reservation(
            reservation_code=code,
            customer_id=customer.id,
            branch_id=data.branch_id,
            status=ReservationStatus.PENDING.value,
            customer_notes=data.customer_notes.strip() if data.customer_notes else None,
            created_at=now,
            expires_at=expires_at,
        )
        db.add(reservation)
        db.flush()

        for item_in in data.items:
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
