import uuid
import secrets
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import settings
from app.models.payment import Payment
from app.models.reservation import Reservation, ReservationStatus
from app.models.branch import Branch
from app.models.user import User, UserRole
from app.models.stock import Stock
from app.models.inventory_movement import InventoryMovement, MovementType
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentPayPalOrderResponse,
    PendingReservationOption,
)
from app.services.paypal_service import PayPalService
from app.services.activity_log_service import ActivityLogService
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException

logger = logging.getLogger("payments")


class PaymentService:

    @classmethod
    def _generate_code(cls, db: Session) -> str:
        for _ in range(10):
            token = secrets.token_hex(3).upper()
            code = f"PAY-{token}"
            exists = db.query(Payment).filter(Payment.payment_code == code).first()
            if not exists:
                return code
        return f"PAY-{uuid.uuid4().hex[:6].upper()}"

    @classmethod
    def _enrich_payment(cls, p: Payment) -> PaymentResponse:
        branch_name = p.branch.name if p.branch else None
        res_code = p.reservation.reservation_code if p.reservation else None
        cashier_name = p.cashier.full_name if p.cashier else None

        parsed_items = None
        if p.items_detail:
            try:
                import json
                parsed_items = json.loads(p.items_detail)
            except Exception:
                parsed_items = None

        return PaymentResponse(
            id=p.id,
            payment_code=p.payment_code,
            branch_id=p.branch_id,
            branch_name=branch_name,
            reservation_id=p.reservation_id,
            reservation_code=res_code,
            customer_id=p.customer_id,
            customer_name=p.customer_name,
            customer_email=p.customer_email,
            concept=p.concept,
            amount=float(p.amount) if p.amount is not None else 0.0,
            currency=p.currency,
            payment_type=p.payment_type,
            status=p.status,
            reference=p.reference,
            paypal_order_id=p.paypal_order_id,
            paypal_capture_id=p.paypal_capture_id,
            cashier_id=p.cashier_id,
            cashier_name=cashier_name,
            items_detail=p.items_detail,
            items=parsed_items,
            notes=p.notes,
            created_at=p.created_at,
            paid_at=p.paid_at,
        )

    @classmethod
    def list_payments(
        cls,
        db: Session,
        user: User,
        branch_id: Optional[str] = None,
        status: Optional[str] = None,
        payment_type: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[PaymentResponse]:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

        # Auto-sync pending PayPal payments with Sandbox
        pending_paypal_q = db.query(Payment).filter(
            Payment.status == "PENDING",
            Payment.paypal_order_id.isnot(None),
        )
        if user_role in (UserRole.STORE_MANAGER.value, UserRole.CASHIER.value) and user.branch_id:
            pending_paypal_q = pending_paypal_q.filter(Payment.branch_id == user.branch_id)
        elif branch_id:
            pending_paypal_q = pending_paypal_q.filter(Payment.branch_id == branch_id)

        for p_pend in pending_paypal_q.limit(10).all():
            try:
                order_info = PayPalService.get_order(p_pend.paypal_order_id)
                st = order_info.get("status")
                if st in ("APPROVED", "COMPLETED"):
                    cls.capture_paypal_payment(
                        db=db,
                        user=user,
                        payment_id=p_pend.id,
                        paypal_order_id=p_pend.paypal_order_id,
                    )
            except Exception as ex:
                logger.warning(f"Auto-sync PayPal order {p_pend.paypal_order_id} falló: {str(ex)}")

        query = db.query(Payment)

        if user_role in (UserRole.STORE_MANAGER.value, UserRole.CASHIER.value):
            if user.branch_id:
                query = query.filter(Payment.branch_id == user.branch_id)
        elif branch_id:
            query = query.filter(Payment.branch_id == branch_id)

        if status:
            query = query.filter(Payment.status == status)

        if payment_type:
            query = query.filter(Payment.payment_type == payment_type)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Payment.payment_code.ilike(term),
                    Payment.customer_name.ilike(term),
                    Payment.concept.ilike(term),
                    Payment.reference.ilike(term),
                )
            )

        payments = query.order_by(Payment.created_at.desc()).offset(offset).limit(limit).all()
        return [cls._enrich_payment(p) for p in payments]

    @classmethod
    def get_payment(cls, db: Session, payment_id: str, user: User) -> PaymentResponse:
        p = db.query(Payment).filter(Payment.id == payment_id).first()
        if not p:
            raise NotFoundException(detail="Cobro no encontrado")
        return cls._enrich_payment(p)

    @classmethod
    def _deduct_direct_sale_stock(
        cls,
        db: Session,
        p: Payment,
        user_id: Optional[str],
        now: datetime,
    ) -> None:
        if not p.items_detail:
            return

        import json
        try:
            sale_items = json.loads(p.items_detail)
        except Exception:
            sale_items = []

        for item in sale_items:
            var_id = item.get("variant_id")
            if not var_id:
                continue
            qty = int(item.get("quantity", 1))
            item_amt = float(item.get("subtotal") or (qty * float(item.get("unit_price", 0))))

            stk = db.query(Stock).filter(
                Stock.variant_id == var_id,
                Stock.branch_id == p.branch_id,
            ).first()

            prev_qty = stk.quantity if stk else 0
            new_qty = max(0, prev_qty - qty)
            if stk:
                stk.quantity = new_qty
                stk.updated_at = now

            existing_exit = db.query(InventoryMovement).filter(
                InventoryMovement.reference_number == p.payment_code,
                InventoryMovement.variant_id == var_id,
                InventoryMovement.type == MovementType.EXIT.value,
            ).first()

            p_name = item.get("product_name") or "Prenda"
            if not existing_exit:
                mov = InventoryMovement(
                    variant_id=var_id,
                    branch_id=p.branch_id,
                    type=MovementType.EXIT.value,
                    quantity=qty,
                    reason=f"Venta directa en caja ({p.payment_code}): {p_name}",
                    reference_number=p.payment_code,
                    previous_stock=prev_qty,
                    new_stock=new_qty,
                    user_id=user_id or p.cashier_id,
                    payment_method=p.payment_type,
                    payment_status="PAID",
                    amount=item_amt,
                    paypal_order_id=p.paypal_order_id,
                    paypal_capture_id=p.paypal_capture_id,
                )
                db.add(mov)
            else:
                existing_exit.payment_method = p.payment_type
                existing_exit.payment_status = "PAID"
                if not existing_exit.amount or existing_exit.amount == 0:
                    existing_exit.amount = item_amt

    @classmethod
    def create_payment(
        cls,
        db: Session,
        user: User,
        data: PaymentCreate,
    ) -> PaymentResponse:
        branch = db.query(Branch).filter(Branch.id == data.branch_id).first()
        if not branch:
            raise NotFoundException(detail="Sucursal no encontrada")

        customer_id = None
        if data.reservation_id:
            r = db.query(Reservation).filter(Reservation.id == data.reservation_id).first()
            if r:
                customer_id = r.customer_id
                if not data.customer_name and r.customer:
                    data.customer_name = r.customer.full_name

        items_json_str = None
        amount_final = round(data.amount, 2)
        concept_final = data.concept.strip()

        # Handle direct sale items with branch stock validation and total calculation
        if data.items and len(data.items) > 0:
            import json
            items_list_dict = []
            calc_amount = 0.0
            concept_parts = []
            for itm in data.items:
                stk = db.query(Stock).filter(
                    Stock.variant_id == itm.variant_id,
                    Stock.branch_id == data.branch_id,
                ).first()
                curr_stock = stk.quantity if stk else 0
                if itm.quantity > curr_stock:
                    raise BadRequestException(
                        detail=f"Stock insuficiente para {itm.product_name or 'producto'}: disponible {curr_stock}, solicitado {itm.quantity}"
                    )
                line_subtotal = round(itm.quantity * itm.unit_price, 2)
                calc_amount += line_subtotal
                concept_parts.append(f"{itm.quantity}x {itm.product_name or 'Prenda'}")
                items_list_dict.append({
                    "variant_id": itm.variant_id,
                    "product_name": itm.product_name or "Prenda",
                    "sku": itm.sku or "",
                    "size": itm.size or "",
                    "color": itm.color or "",
                    "quantity": itm.quantity,
                    "unit_price": round(itm.unit_price, 2),
                    "subtotal": line_subtotal,
                })
            items_json_str = json.dumps(items_list_dict)
            if calc_amount > 0:
                amount_final = round(calc_amount, 2)
            if concept_parts:
                concept_final = f"Venta: {', '.join(concept_parts)}"[:255]

        payment = Payment(
            payment_code=cls._generate_code(db),
            branch_id=data.branch_id,
            reservation_id=data.reservation_id,
            customer_id=customer_id,
            customer_name=data.customer_name.strip(),
            customer_email=data.customer_email.strip() if data.customer_email else None,
            concept=concept_final,
            amount=amount_final,
            currency=data.currency or "EUR",
            payment_type=data.payment_type or "EFECTIVO",
            status="PENDING",
            reference="Pendiente en Caja",
            cashier_id=user.id,
            items_detail=items_json_str,
            notes=data.notes.strip() if data.notes else None,
            created_at=datetime.now(timezone.utc),
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)

        ActivityLogService.log_event(
            db=db,
            user=user,
            action="CREAR_ORDEN_COBRO",
            description=f"Orden de cobro #{payment.payment_code} creada por ${payment.amount:.2f} {payment.currency} ({payment.payment_type}) para cliente {payment.customer_name}",
            category="FINANZAS",
        )

        return cls._enrich_payment(payment)

    @classmethod
    def process_cash_payment(
        cls,
        db: Session,
        user: User,
        payment_id: str,
        notes: Optional[str] = None,
    ) -> PaymentResponse:
        p = db.query(Payment).filter(Payment.id == payment_id).first()
        if not p:
            raise NotFoundException(detail="Cobro no encontrado")

        if p.status == "PAID":
            return cls._enrich_payment(p)

        now = datetime.now(timezone.utc)
        p.status = "PAID"
        p.payment_type = "EFECTIVO"
        p.reference = f"Caja Local ({user.full_name or 'Caja'})"
        p.cashier_id = user.id
        p.paid_at = now
        if notes:
            p.notes = f"{p.notes or ''} | {notes}".strip(" |")

        # If linked to a reservation, complete it and register EXIT movements in inventory
        if p.reservation_id:
            r = db.query(Reservation).filter(Reservation.id == p.reservation_id).first()
            if r:
                r.payment_method = "EFECTIVO"
                r.payment_status = "PAID"
                r.status = ReservationStatus.COMPLETED.value
                r.paid_at = now
                if not r.staff_notes:
                    r.staff_notes = f"Cobrado en efectivo en caja ({p.payment_code})"

                # Emit EXIT movements in inventory_movements (CU09)
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
                            reason=f"Venta en caja (Efectivo) por reserva ({r.reservation_code})",
                            reference_number=r.reservation_code,
                            previous_stock=curr_qty + item.quantity,
                            new_stock=curr_qty,
                            user_id=user.id,
                            payment_method="EFECTIVO",
                            payment_status="PAID",
                            amount=item_amount,
                        )
                        db.add(mov)
                    else:
                        existing_exit.payment_method = "EFECTIVO"
                        existing_exit.payment_status = "PAID"
                        if not existing_exit.amount or existing_exit.amount == 0:
                            existing_exit.amount = item_amount

        # If direct sale with items, deduct stock in branch and register EXIT movements (CU09)
        cls._deduct_direct_sale_stock(db=db, p=p, user_id=user.id, now=now)

        db.commit()
        db.refresh(p)

        ActivityLogService.log_event(
            db=db,
            user=user,
            action="COBRO_EFECTIVO",
            description=f"Cobro en efectivo liquidado exitosamente #{p.payment_code} por ${p.amount:.2f} {p.currency} en caja de sucursal",
            category="FINANZAS",
        )

        return cls._enrich_payment(p)

    @classmethod
    def create_paypal_checkout(
        cls,
        db: Session,
        user: User,
        payment_id: str,
    ) -> PaymentPayPalOrderResponse:
        p = db.query(Payment).filter(Payment.id == payment_id).first()
        if not p:
            raise NotFoundException(detail="Cobro no encontrado")

        if p.status == "PAID":
            raise BadRequestException(detail="Este cobro ya ha sido pagado previamente")

        amount_val = float(p.amount)
        currency_val = p.currency or "USD"
        concept_clean = p.concept[:120] if p.concept else f"Cobro {p.payment_code}"

        try:
            # Redirigir al resumen de cuenta en PayPal Sandbox para que el usuario permanezca en PayPal
            sandbox_summary = "https://www.sandbox.paypal.com/myaccount/summary?intl=0"
            paypal_result = PayPalService.create_order(
                amount=amount_val,
                currency=currency_val,
                description=f"Caja {p.payment_code}: {concept_clean}",
                return_url=sandbox_summary,
                cancel_url=sandbox_summary,
                custom_id=p.id,
            )
        except Exception as e:
            logger.error(f"Error al generar orden en PayPal: {str(e)}")
            raise BadRequestException(detail=f"Error al conectar con PayPal Sandbox: {str(e)}")

        paypal_order_id = paypal_result.get("order_id") or paypal_result.get("id")
        approval_url = paypal_result["approval_url"]

        p.paypal_order_id = paypal_order_id
        p.payment_type = "PAYPAL"
        p.reference = paypal_order_id
        db.commit()
        db.refresh(p)

        return PaymentPayPalOrderResponse(
            payment_id=p.id,
            order_id=paypal_order_id,
            approval_url=approval_url,
            amount=amount_val,
            currency=currency_val,
        )

    @classmethod
    def capture_paypal_by_order_id(cls, db: Session, paypal_order_id: str) -> PaymentResponse:
        p = db.query(Payment).filter(Payment.paypal_order_id == paypal_order_id).first()
        if not p:
            raise NotFoundException(detail="No se encontró ningún cobro para esta orden de PayPal")
        return cls.capture_paypal_payment(db=db, user=None, payment_id=p.id, paypal_order_id=paypal_order_id)

    @classmethod
    def capture_paypal_payment(
        cls,
        db: Session,
        user: Optional[User],
        payment_id: str,
        paypal_order_id: str,
    ) -> PaymentResponse:
        p = db.query(Payment).filter(Payment.id == payment_id).first()
        if not p:
            raise NotFoundException(detail="Cobro no encontrado")

        if p.status == "PAID":
            return cls._enrich_payment(p)

        # Check PayPal order status first
        order_info = PayPalService.get_order(paypal_order_id)
        current_paypal_status = order_info.get("status")
        capture_id = None
        capture_status = "UNKNOWN"

        if current_paypal_status == "COMPLETED":
            capture_status = "COMPLETED"
            pu = order_info.get("purchase_units", [])
            if pu:
                captures = pu[0].get("payments", {}).get("captures", [])
                if captures:
                    capture_id = captures[0].get("id")
        elif current_paypal_status in ("APPROVED", "SAVED"):
            try:
                capture_data = PayPalService.capture_order(paypal_order_id)
                capture_status = capture_data.get("status", "UNKNOWN")
                capture_id = capture_data.get("capture_id")
            except Exception as e:
                if "ORDER_ALREADY_CAPTURED" in str(e):
                    capture_status = "COMPLETED"
                else:
                    raise e
        else:
            # Try capturing
            try:
                capture_data = PayPalService.capture_order(paypal_order_id)
                capture_status = capture_data.get("status", "UNKNOWN")
                capture_id = capture_data.get("capture_id")
            except Exception as e:
                if "ORDER_ALREADY_CAPTURED" in str(e):
                    capture_status = "COMPLETED"
                else:
                    raise e

        if capture_status in ("COMPLETED", "APPROVED"):
            now = datetime.now(timezone.utc)
            p.status = "PAID"
            p.payment_type = "PAYPAL"
            p.paypal_order_id = paypal_order_id
            p.paypal_capture_id = capture_id
            p.reference = capture_id or paypal_order_id
            if user:
                p.cashier_id = user.id
            p.paid_at = now

            # If linked to a reservation, complete it and register EXIT movements in inventory
            if p.reservation_id:
                r = db.query(Reservation).filter(Reservation.id == p.reservation_id).first()
                if r:
                    r.payment_method = "PAYPAL"
                    r.payment_status = "PAID"
                    r.status = ReservationStatus.COMPLETED.value
                    r.paypal_order_id = paypal_order_id
                    r.paypal_capture_id = capture_id
                    r.paid_at = now
                    if not r.staff_notes:
                        r.staff_notes = f"Cobrado con PayPal en caja ({p.payment_code})"

                    # Emit EXIT movements in inventory_movements (CU09)
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
                                reason=f"Venta en caja (PayPal) por reserva ({r.reservation_code})",
                                reference_number=r.reservation_code,
                                previous_stock=curr_qty + item.quantity,
                                new_stock=curr_qty,
                                user_id=user.id,
                                payment_method="PAYPAL",
                                payment_status="PAID",
                                amount=item_amount,
                                paypal_order_id=paypal_order_id,
                                paypal_capture_id=capture_id,
                            )
                            db.add(mov)
                        else:
                            existing_exit.payment_method = "PAYPAL"
                            existing_exit.payment_status = "PAID"
                            existing_exit.paypal_order_id = paypal_order_id
                            existing_exit.paypal_capture_id = capture_id
                            if not existing_exit.amount or existing_exit.amount == 0:
                                existing_exit.amount = item_amount

            # If direct sale with items, deduct stock in branch and register EXIT movements (CU09)
            cls._deduct_direct_sale_stock(db=db, p=p, user_id=user.id if user else None, now=now)

            db.commit()
            db.refresh(p)

            ActivityLogService.log_event(
                db=db,
                user=user,
                action="COBRO_PAYPAL",
                description=f"Cobro PayPal capturado exitosamente #{p.payment_code} por ${p.amount:.2f} {p.currency} (Order: {paypal_order_id})",
                category="FINANZAS",
            )
        else:
            raise BadRequestException(detail=f"La captura de PayPal retornó estado: {capture_status}")

        return cls._enrich_payment(p)

    @classmethod
    def get_pending_reservations_for_branch(
        cls,
        db: Session,
        user: User,
        branch_id: str,
    ) -> List[PendingReservationOption]:
        # Active reservations in branch not yet paid
        query = (
            db.query(Reservation)
            .filter(
                Reservation.branch_id == branch_id,
                Reservation.payment_status == "PENDING",
                Reservation.status.in_([ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value]),
            )
            .order_by(Reservation.created_at.desc())
        )
        reservations = query.all()
        results = []
        for r in reservations:
            items_desc = ", ".join(
                [f"{it.quantity}x {it.variant.product.name if it.variant and it.variant.product else 'Prenda'}" for it in r.items[:3]]
            )
            if len(r.items) > 3:
                items_desc += f" y {len(r.items) - 3} más..."

            customer_name = r.customer.full_name if r.customer else "Cliente General"
            customer_email = r.customer.email if r.customer else None
            tot_items = sum(it.quantity for it in r.items)
            tot_amount = float(r.total_amount or 0.0)
            if tot_amount == 0.0:
                for it in r.items:
                    v = it.variant
                    if v and v.product and v.product.price:
                        tot_amount += float(v.product.price) * it.quantity

            results.append(
                PendingReservationOption(
                    reservation_id=r.id,
                    reservation_code=r.reservation_code,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    branch_id=r.branch_id,
                    branch_name=r.branch.name if r.branch else None,
                    total_items=tot_items,
                    total_amount=round(tot_amount, 2),
                    items_summary=items_desc,
                    status=r.status,
                    payment_status=r.payment_status,
                )
            )
        return results
