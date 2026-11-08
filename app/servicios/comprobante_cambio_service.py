"""Immutable reservation pricing and one stable receipt code across mobile/web."""
import json
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import or_
from app.modelos.reserva import Reserva
from app.modelos.pago import Pago
from app.modelos.movimiento_inventario import MovimientoInventario
from app.modelos.aporte_propio import CambioPrenda
from app.nucleo.ambito_sucursal import resolve_branch


def normalize(code):
    code = code.strip().upper()
    for prefix in ('REC-', 'FAC-'):
        if code.startswith(prefix):
            code = code[len(prefix):]
    return code


def freeze_quote(reservation):
    from app.nucleo.fidelizacion import snapshot
    from app.servicios.aporte_propio_service import price, money
    if reservation.receipt_items_detail is None and reservation.items and reservation.total_amount is not None:
        reservation.receipt_items_detail = json.dumps(snapshot(reservation, reservation.total_amount, price, money))


def reservation_items(db, reservation, payments):
    from app.servicios.aporte_propio_service import money, fail
    total = money(payments[0].amount if payments else reservation.total_amount or 0)
    def checked(items):
        if not items or sum((money(item['subtotal']) for item in items), Decimal('0')) != total:
            fail('El detalle del comprobante no coincide con el importe pagado. Revisa el recibo original antes de cambiar prendas.', 409)
        return items
    if reservation.receipt_items_detail:
        return checked(json.loads(reservation.receipt_items_detail))
    for payment in payments:
        if payment.items_detail and json.loads(payment.items_detail):
            return checked(json.loads(payment.items_detail))
    # Legacy receipts: use historical movement amounts, never today's prices.
    movements = db.query(MovimientoInventario).filter(
        MovimientoInventario.reference_number.in_([reservation.reservation_code] + [p.payment_code for p in payments]),
        MovimientoInventario.branch_id == reservation.branch_id,
        MovimientoInventario.type == 'EXIT', MovimientoInventario.payment_status == 'PAID',
    ).all()
    total = money(payments[0].amount if payments else reservation.total_amount or 0)
    items = []
    for item in sorted(reservation.items, key=lambda line: line.id):
        movement = next((m for m in movements if m.variant_id == item.variant_id and m.quantity == item.quantity and m.amount is not None), None)
        subtotal = money(movement.amount) if movement else total if len(reservation.items) == 1 else None
        if subtotal is None:
            fail('El comprobante histórico no conserva precios suficientes para calcular el cambio. Revisa el recibo original.', 409)
        v = item.variant
        items.append(dict(variant_id=item.variant_id, quantity=item.quantity,
            unit_price=float(money(subtotal / item.quantity)), subtotal=float(subtotal),
            product_name=v.product.name, size=v.size.name, color=v.color.name, sku=v.sku))
    if not items or sum((money(i['subtotal']) for i in items), Decimal('0')) != total:
        fail('El detalle histórico no coincide con el importe pagado. Revisa el comprobante original antes de cambiar prendas.', 409)
    return items


def validate_deadline(issued_at):
    from app.servicios.aporte_propio_service import aware, now, fail
    if not issued_at:
        fail('El comprobante no tiene fecha de emisión confirmada.', 409)
    deadline = aware(issued_at) + timedelta(hours=48)
    if aware(now()) > deadline:
        fail('Pasó el límite de cambio de 48 horas desde la emisión del recibo.', 409)
    return deadline


def source(db, user, payment_id=None, reservation_id=None, lock=False, enforce_deadline=True):
    from app.servicios.aporte_propio_service import fail, aware
    if reservation_id:
        query = db.query(Reserva).filter(Reserva.id == reservation_id)
        if lock:
            query = query.with_for_update(of=Reserva).populate_existing()
        r = query.first()
        if not r or r.payment_status != 'PAID':
            fail('Reserva pagada no encontrada.', 404)
        if user.role == 'CUSTOMER':
            if r.customer_id != user.id:
                fail('Compra no encontrada.', 404)
        else:
            resolve_branch(user, r.branch_id)
        deadline = validate_deadline(r.paid_at) if enforce_deadline else None
        payments = db.query(Pago).filter(Pago.reservation_id == r.id, Pago.status == 'PAID').order_by(Pago.paid_at).all()
        p = payments[0] if payments else None
        from app.modelos.usuario import Usuario
        buyer = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == r.customer_id).first()
        result = dict(id=r.id, source='reservation', reservation_id=r.id,
            payment_id=p.id if p else None, code=r.reservation_code, branch_id=r.branch_id,
            customer_id=r.customer_id, customer_name=buyer.full_name if buyer else 'Cliente',
            customer_email=buyer.email if buyer else None,
            customer_phone=buyer.phone if buyer else None,
            currency=p.currency if p else 'USD', amount=p.amount if p else r.total_amount,
            paid_at=r.paid_at, receipt_issued_at=aware(r.paid_at) if r.paid_at else None, exchange_deadline=deadline,
            items=reservation_items(db, r, payments))
    else:
        query = db.query(Pago).filter(Pago.id == payment_id)
        if lock:
            query = query.with_for_update(of=Pago).populate_existing()
        p = query.first()
        if not p or p.status != 'PAID' or not p.items_detail:
            fail('Compra pagada con detalle no encontrada.', 404)
        # A linked reservation always uses its stable RSV code and expiry.
        if p.reservation_id:
            return source(db, user, reservation_id=p.reservation_id, lock=lock, enforce_deadline=enforce_deadline)
        if user.role == 'CUSTOMER':
            if p.customer_id != user.id:
                fail('Compra no encontrada.', 404)
        else:
            resolve_branch(user, p.branch_id)
        deadline = validate_deadline(p.paid_at) if enforce_deadline else None
        result = dict(id=p.id, source='payment', reservation_id=None, payment_id=p.id,
            code=p.payment_code, branch_id=p.branch_id, customer_id=p.customer_id,
            customer_name=p.customer_name, customer_email=p.customer_email, customer_phone=None,
            currency=p.currency, amount=p.amount, paid_at=p.paid_at, receipt_issued_at=aware(p.paid_at) if p.paid_at else None,
            exchange_deadline=deadline, items=json.loads(p.items_detail))
    condition = CambioPrenda.payment_id == result['payment_id'] if result['payment_id'] else None
    if result['reservation_id']:
        linked = db.query(Pago.id).filter(Pago.reservation_id == result['reservation_id'])
        condition = or_(CambioPrenda.reservation_id == result['reservation_id'], CambioPrenda.payment_id.in_(linked))
    used = {}
    credited = {}
    for change in db.query(CambioPrenda).filter(condition):
        used[change.original_line] = used.get(change.original_line, 0) + change.quantity
        credited[change.original_line] = credited.get(change.original_line, Decimal('0')) + change.new_unit_price * change.quantity - change.difference
    result['items'] = [dict(item, line=i, credited_amount=float(credited.get(i, 0)), available_to_exchange=max(0, int(item['quantity']) - used.get(i, 0)))
                       for i, item in enumerate(result['items'])]
    return result


def search(db, user, code=''):
    from fastapi import HTTPException
    from app.servicios.aporte_propio_service import fail, aware, now
    normalized = normalize(code)
    exact = normalized.startswith(('RSV-', 'PAY-', 'CAM-'))
    payments = db.query(Pago).filter(Pago.status == 'PAID', Pago.items_detail.isnot(None), Pago.reservation_id.is_(None))
    reservations = db.query(Reserva).filter(Reserva.payment_status == 'PAID')
    if user.role == 'CUSTOMER':
        payments = payments.filter(Pago.customer_id == user.id)
        reservations = reservations.filter(Reserva.customer_id == user.id)
    else:
        branch = resolve_branch(user)
        if branch:
            payments = payments.filter(Pago.branch_id == branch)
            reservations = reservations.filter(Reserva.branch_id == branch)
    if normalized:
        if exact:
            from sqlalchemy import func
            payments = payments.filter(func.upper(Pago.payment_code) == normalized)
            linked = db.query(Pago.reservation_id).filter(func.upper(Pago.payment_code) == normalized)
            reservations = reservations.filter(or_(func.upper(Reserva.reservation_code) == normalized, Reserva.id.in_(linked)))
        else:
            payments = payments.filter(Pago.customer_name.ilike('%' + code.strip() + '%'))
            from app.modelos.usuario import Usuario
            reservations = reservations.join(Reserva.customer).filter(Usuario.full_name.ilike('%' + code.strip() + '%'))
    result = []
    for row, is_reservation in [(p, False) for p in payments.order_by(Pago.paid_at.desc()).limit(100)] + [(r, True) for r in reservations.order_by(Reserva.paid_at.desc()).limit(100)]:
        try:
            result.append(source(db, user, reservation_id=row.id if is_reservation else None,
                                 payment_id=None if is_reservation else row.id))
        except HTTPException:
            if exact:
                raise
            continue  # Listing shows only eligible, reconstructible receipts.
    if exact and not result:
        fail('No se encontró una compra pagada con ese código en esta empresa y sucursal.', 404)
    return sorted(result, key=lambda row: aware(row['paid_at']), reverse=True)[:100]
