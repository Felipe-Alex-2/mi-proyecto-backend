from app.nucleo.transacciones import commit_or_flush
"""Company scoped points and single-use rewards, reserved atomically at checkout."""
import json
import secrets
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import func
from app.modelos.aporte_propio import BeneficioPuntos, MovimientoPuntos
from app.modelos.usuario import Usuario
from app.modelos.saas import ClienteEmpresa
from app.modelos.pago import Pago

OPTIONS = [dict(id='COUPON_7', points=5, percent=7, name='Cupón 7%'),
           dict(id='COUPON_10', points=7, percent=10, name='Cupón 10%'),
           dict(id='COUPON_15', points=10, percent=15, name='Cupón 15%'),
           dict(id='MYSTERY', points=10, percent=0, name='Caja de prenda misteriosa')]


def helpers():
    from app.servicios import aporte_propio_service as s
    return s


def loyalty(db, user):
    s = helpers()
    return dict(balance=s.balance(db, user.id), dollars_per_point=10, options=OPTIONS,
                entries=[s.serialize(r) for r in db.query(MovimientoPuntos).filter(
                    MovimientoPuntos.customer_id == user.id).order_by(MovimientoPuntos.created_at.desc()).limit(100)],
                rewards=[s.serialize(r) for r in db.query(BeneficioPuntos).filter(
                    BeneficioPuntos.customer_id == user.id).order_by(BeneficioPuntos.created_at.desc()).limit(100)])


def leaderboard(db):
    # No reward codes or balances from other companies leave this endpoint.
    totals = db.query(MovimientoPuntos.customer_id.label('customer_id'),
        func.sum(MovimientoPuntos.points).label('points')).filter(MovimientoPuntos.tenant_id == db.info['tenant_id']).group_by(MovimientoPuntos.customer_id).subquery()
    score = func.coalesce(totals.c.points, 0)
    rows = db.query(Usuario.id, Usuario.full_name, score.label('points')).join(
        ClienteEmpresa, ClienteEmpresa.user_id == Usuario.id).outerjoin(totals, totals.c.customer_id == Usuario.id).filter(
        ClienteEmpresa.tenant_id == db.info['tenant_id'], Usuario.role == 'CUSTOMER').order_by(
        score.desc(), Usuario.full_name, Usuario.id).all()
    return [dict(customer_id=r.id, customer_name=r.full_name, points=int(r.points)) for r in rows]


def redeem(db, user, data):
    s = helpers()
    old, attrs = s.start(db, user, data, BeneficioPuntos)
    if old:
        return s.serialize(old)
    option = next(o for o in OPTIONS if o['id'] == data.reward)
    db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == user.id).with_for_update().first()
    if s.balance(db, user.id) < option['points']:
        s.fail(f"Necesitas {option['points']} puntos disponibles.", 409)
    row = BeneficioPuntos(**attrs, customer_id=user.id, code='VESTA-' + secrets.token_hex(8).upper(),
        reward_type='MYSTERY' if data.reward == 'MYSTERY' else 'COUPON', points_cost=option['points'],
        discount_percent=option['percent'], max_discount=None, status='AVAILABLE',
        expires_at=s.now() + timedelta(days=30), discount_amount=0)
    # SQLAlchemy's legacy default is 20; explicitly assign null after insert below.
    db.add(row)
    db.flush()
    row.max_discount = None
    db.add(MovimientoPuntos(tenant_id=attrs['tenant_id'], customer_id=user.id,
        source_key='redeem:' + row.id, points=-option['points'], description='Canje: ' + option['name']))
    s.audit(db, user, 'REGISTRO_CANJE_PUNTOS', f"Beneficio {row.id}: {option['name']}, {option['points']} puntos")
    commit_or_flush(db)
    return s.serialize(row)


def coupon(db, customer_id, code):
    s = helpers()
    row = db.query(BeneficioPuntos).filter(BeneficioPuntos.code == code.strip().upper()).with_for_update().populate_existing().first()
    if not row or not customer_id or row.customer_id != customer_id:
        s.fail('Cupón inválido para el cliente de esta compra.', 404)
    if row.reward_type != 'COUPON':
        s.fail('La caja misteriosa solo se retira presencialmente; no es un cupón.')
    if row.status != 'AVAILABLE' or s.aware(row.expires_at) <= s.now():
        s.fail('El cupón ya fue utilizado, está reservado en otra compra o venció.', 409)
    return row


def discount(items, reward, currency='USD'):
    s = helpers()
    if any(i.get('wholesale_discount_percent', 0) for i in items):
        s.fail('Esta compra ya tiene 15% por mayor. Conserva tu cupón para otra compra.')
    if reward.max_discount is not None and currency != 'BOB':
        s.fail('Este cupón antiguo solo es válido para ventas en BOB.')
    total = sum((s.money(i['subtotal']) for i in items), Decimal(0))
    savings = s.money(total * reward.discount_percent / 100)
    if reward.max_discount is not None:
        savings = min(savings, s.money(reward.max_discount))
    if savings <= 0 or savings >= total:
        s.fail('El importe no permite aplicar este cupón.')
    net = total - savings
    gross_so_far = Decimal(0)
    allocated = Decimal(0)
    result = []
    for item in items:
        gross = s.money(item['subtotal'])
        gross_so_far += gross
        cumulative = s.money(net * gross_so_far / total)
        line_net = cumulative - allocated
        allocated = cumulative
        result.append(dict(item, coupon_original_unit_price=item['unit_price'], coupon_original_subtotal=float(gross),
            coupon_discount_percent=reward.discount_percent, coupon_discount_amount=float(gross-line_net),
            unit_price=float(line_net / item['quantity']), subtotal=float(line_net)))
    return result, net, savings


def quote(db, user, data):
    s = helpers()
    from app.servicios.venta_mayor_service import reservation_quote
    from app.modelos.stock import Stock
    s.branch(db, data.branch_id)
    customer_id = user.id
    if user.role != 'CUSTOMER':
        s.resolve_branch(user, data.branch_id)
        customer = db.query(Usuario).join(ClienteEmpresa, ClienteEmpresa.user_id == Usuario.id).filter(
            ClienteEmpresa.tenant_id == db.info['tenant_id'], Usuario.role == 'CUSTOMER',
            Usuario.email == (data.customer_email or '').strip().lower()).first()
        customer_id = customer.id if customer else None
    seen = set()
    for item in data.items:
        if item.variant_id in seen:
            s.fail('Agrupa las cantidades de una misma variante.')
        seen.add(item.variant_id)
        stock = db.query(Stock).filter(Stock.branch_id == data.branch_id, Stock.variant_id == item.variant_id).first()
        if not stock or not stock.variant.is_active or not stock.variant.product.is_active or stock.quantity < item.quantity:
            s.fail('Stock insuficiente para aplicar el cupón.', 409)
    reward = coupon(db, customer_id, data.code)
    items, _ = reservation_quote(db, data.items)
    items, total, savings = discount(items, reward)
    return dict(items=items, total_amount=total, coupon_discount_amount=savings, discount_percent=reward.discount_percent)


def bind(reward, payment=None, reservation=None, savings=0):
    reward.status = 'RESERVED'
    reward.payment_id = payment.id if payment else None
    reward.reservation_id = reservation.id if reservation else None
    reward.discount_amount = savings


def apply_reward(db, user, data):
    s = helpers()
    p = db.query(Pago).filter(Pago.id == data.payment_id).with_for_update(of=Pago).populate_existing().first()
    if not p:
        s.fail('Cobro no encontrado.', 404)
    s.resolve_branch(user, p.branch_id)
    existing = db.query(BeneficioPuntos).filter(BeneficioPuntos.payment_id == p.id).first()
    if existing:
        if existing.code != data.code.strip().upper():
            s.fail('Esta compra ya tiene un cupón.', 409)
        return dict(status=existing.status, discount_amount=existing.discount_amount)
    if p.status != 'PENDING' or p.paypal_order_id or p.reservation_id or not p.items_detail:
        s.fail('Aplica el cupón a una venta directa pendiente antes de iniciar su pago.')
    reward = coupon(db, p.customer_id, data.code)
    items, total, savings = discount(json.loads(p.items_detail), reward, p.currency)
    p.amount, p.items_detail = total, json.dumps(items)
    bind(reward, payment=p, savings=savings)
    commit_or_flush(db)
    return dict(status=reward.status, discount_amount=reward.discount_amount)


def claim(db, user, data):
    s = helpers()
    s.resolve_branch(user, data.branch_id)
    s.branch(db, data.branch_id)
    reward = db.query(BeneficioPuntos).filter(BeneficioPuntos.code == data.code.strip().upper()).with_for_update().populate_existing().first()
    if not reward or reward.reward_type != 'MYSTERY':
        s.fail('Código de caja misteriosa inválido.', 404)
    if reward.status == 'CLAIMED':
        if reward.fulfilled_branch_id != data.branch_id or reward.fulfilled_variant_id != data.variant_id:
            s.fail('La caja ya fue entregada.', 409)
        return dict(status='CLAIMED')
    if reward.status != 'AVAILABLE' or s.aware(reward.expires_at) <= s.now():
        s.fail('Este canje venció o ya no está disponible.', 409)
    variants, stock = s.stocks(db, [data.variant_id], [data.branch_id])
    if not variants[data.variant_id].is_active or not variants[data.variant_id].product.is_active:
        s.fail('La prenda está inactiva.', 409)
    row = stock.get((data.branch_id, data.variant_id))
    if not row or row.quantity < 1:
        s.fail('La prenda seleccionada no tiene stock.', 409)
    s.move(db, user, stock, data.branch_id, data.variant_id, -1, reward.id, 'Retiro presencial de caja misteriosa')
    reward.status, reward.fulfilled_branch_id, reward.fulfilled_variant_id = 'CLAIMED', data.branch_id, data.variant_id
    reward.fulfilled_by, reward.fulfilled_at = user.id, s.now()
    s.audit(db, user, 'ENTREGA_CAJA_MISTERIOSA', f'Beneficio {reward.id}; prenda {data.variant_id}', data.branch_id)
    commit_or_flush(db)
    return dict(status='CLAIMED')


def settle(db, obj):
    """Called by before_flush; never commits and never creates a second sale."""
    from app.modelos.reserva import Reserva
    from sqlalchemy import or_
    payment = isinstance(obj, Pago)
    filters = [BeneficioPuntos.payment_id == obj.id] if payment else [BeneficioPuntos.reservation_id == obj.id]
    if payment and obj.reservation_id:
        filters.append(BeneficioPuntos.reservation_id == obj.reservation_id)
    rewards = db.query(BeneficioPuntos).filter(or_(*filters), BeneficioPuntos.status == 'RESERVED').with_for_update().all()
    paid = obj.status == 'PAID' if payment else obj.payment_status == 'PAID'
    canceled = obj.status in ('CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED')
    for reward in rewards:
        if paid:
            reward.status = 'USED'
        elif canceled and (not payment or reward.payment_id == obj.id):
            reward.status = 'AVAILABLE'
            reward.payment_id = reward.reservation_id = None
            reward.discount_amount = 0
