"""Accrue once at settlement, in the same database transaction as the purchase."""
import json
import uuid
from decimal import Decimal
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

_installed = False


def install_loyalty_events():
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, 'before_flush')
    def accrue(db, flush_context, instances):
        from app.modelos.pago import Pago
        from app.modelos.reserva import Reserva
        from app.modelos.usuario import Usuario
        from app.modelos.aporte_propio import MovimientoPuntos
        from app.modelos.saas import ROOT_TENANT_ID
        from app.servicios.aporte_propio_service import price, money

        for obj in list(db.new) + list(db.dirty):
            if not isinstance(obj, (Pago, Reserva)):
                continue
            paid = obj.status == 'PAID' if isinstance(obj, Pago) else obj.payment_status == 'PAID'
            if not paid or not obj.customer_id:
                continue
            state_field = 'status' if isinstance(obj, Pago) else 'payment_status'
            if obj not in db.new and not inspect(obj).attrs[state_field].history.has_changes():
                continue  # Editing an old paid receipt never backfills prices or points.
            tenant_id = obj.tenant_id or db.info.get('tenant_id') or ROOT_TENANT_ID
            obj.id = obj.id or str(uuid.uuid4())
            # Reservation settlement gets an immutable detail snapshot too. This
            # keeps the customer's online purchases usable for exchanges/delivery.
            if isinstance(obj, Pago) and obj.reservation_id and not obj.items_detail:
                reservation = db.query(Reserva).execution_options(skip_tenant=True).filter(
                    Reserva.id == obj.reservation_id, Reserva.tenant_id == tenant_id).first()
                if reservation:
                    obj.items_detail = json.dumps(snapshot(reservation, obj.amount, price, money))
            if isinstance(obj, Reserva):
                if not obj.items:
                    continue
                # Existing reservations do not have their own currency column.
                # Only an explicit payment establishes a currency for points.
                payment = next((p for p in db.new if isinstance(p, Pago) and p.reservation_id == obj.id), None)
                if not payment:
                    payment = db.query(Pago).execution_options(skip_tenant=True).filter(
                        Pago.reservation_id == obj.id, Pago.tenant_id == tenant_id).first()
                if not payment:
                    # Reservations without an explicit currency-bearing receipt
                    # remain in their existing flow; never create a second sale.
                    continue
                currency = payment.currency
                amount = payment.amount
                source = 'reservation:' + obj.id
            else:
                currency, amount = obj.currency, obj.amount
                source = 'reservation:' + obj.reservation_id if obj.reservation_id else 'payment:' + obj.id
                try:
                    has_items = bool(json.loads(obj.items_detail or '[]'))
                except (TypeError, ValueError):
                    has_items = False
                if not has_items:
                    continue  # Shipping, differences and generic fees earn no points.
            if currency != 'BOB' or amount is None or Decimal(str(amount)) <= 0:
                continue
            points = int(Decimal(str(amount)) // 10)
            if not points:
                continue
            customer = db.query(Usuario).execution_options(skip_tenant=True).filter(
                Usuario.id == obj.customer_id, Usuario.role == 'CUSTOMER').with_for_update().first()
            if not customer:
                continue
            if any(isinstance(entry, MovimientoPuntos) and entry.tenant_id == tenant_id and
                   entry.customer_id == customer.id and entry.source_key == source for entry in db.new):
                continue
            existing = db.query(MovimientoPuntos).execution_options(skip_tenant=True).filter(
                MovimientoPuntos.tenant_id == tenant_id, MovimientoPuntos.customer_id == customer.id,
                MovimientoPuntos.source_key == source).first()
            if not existing:
                db.add(MovimientoPuntos(tenant_id=tenant_id, customer_id=customer.id,
                       source_key=source, points=points, description=f'Compra pagada: Bs {money(amount)}'))


def snapshot(reservation, total, price_fn, money_fn):
    entries = [(item, price_fn(item.variant)) for item in reservation.items]
    gross = sum((unit * item.quantity for item, unit in entries), Decimal('0'))
    factor = Decimal(str(total)) / gross if gross else Decimal('0')
    return [dict(variant_id=item.variant_id, product_name=item.variant.product.name,
                 quantity=item.quantity, unit_price=float(money_fn(unit * factor)),
                 subtotal=float(money_fn(unit * factor * item.quantity)),
                 size=item.variant.size.name, color=item.variant.color.name, sku=item.variant.sku)
            for item, unit in entries]
