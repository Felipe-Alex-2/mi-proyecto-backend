"""CU19–CU23. Server prices, company scopes and atomic commercial documents."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from fastapi import HTTPException
from sqlalchemy import func, or_
from app.modelos.aporte_propio import CambioPrenda, TrasladoInventario, MovimientoPuntos, BeneficioPuntos, EntregaDomicilio
from app.modelos.saas import Empresa
from app.modelos.usuario import Usuario
from app.modelos.sucursal import Sucursal
from app.modelos.pago import Pago
from app.modelos.stock import Stock
from app.modelos.variante_producto import VarianteProducto
from app.modelos.movimiento_inventario import MovimientoInventario
from app.modelos.bitacora import Bitacora
from app.nucleo.ambito_sucursal import resolve_branch


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def money(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def fail(message, code=422):
    raise HTTPException(code, message)


def serialize(row):
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns
              if column.name != 'request_hash'}
    for name in ['items_json', 'history_json']:
        if name in result:
            result[name.removesuffix('_json')] = json.loads(result.pop(name))
    return result


def start(db, user, data, model):
    # Serializes retries and absent destination stock rows within each company.
    tenant_id = db.info['tenant_id']
    db.query(Empresa).filter(Empresa.id == tenant_id).with_for_update().first()
    digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    previous = db.query(model).filter(model.request_id == str(data.request_id)).first()
    if previous:
        if previous.created_by != user.id or previous.request_hash != digest:
            fail('La solicitud ya se utilizó con otros datos.', 409)
        return previous, None
    return None, dict(id=str(uuid.uuid4()), tenant_id=tenant_id, request_id=str(data.request_id),
                      request_hash=digest, created_by=user.id, created_at=now())


def branch(db, branch_id):
    row = db.query(Sucursal).filter(Sucursal.id == branch_id, Sucursal.is_active == True).first()
    if not row:
        fail('La sucursal no existe, está inactiva o pertenece a otra empresa.', 404)
    return row


def audit(db, user, action, description, branch_id=None):
    b = branch(db, branch_id) if branch_id else None
    db.add(Bitacora(tenant_id=db.info['tenant_id'], user_id=user.id, user_email=user.email,
                    user_name=user.full_name, action=action, description=description,
                    category='APORTE_PROPIO', branch_id=branch_id, branch_name=b.name if b else None))


def stocks(db, variant_ids, branch_ids):
    ids = sorted(set(variant_ids))
    variants = db.query(VarianteProducto).filter(VarianteProducto.id.in_(ids)).order_by(
        VarianteProducto.id).with_for_update().populate_existing().all()
    if len(variants) != len(ids):
        fail('Una variante no pertenece a esta empresa.', 404)
    rows = db.query(Stock).filter(Stock.variant_id.in_(ids), Stock.branch_id.in_(branch_ids)).order_by(
        Stock.branch_id, Stock.variant_id).with_for_update().populate_existing().all()
    return {v.id: v for v in variants}, {(s.branch_id, s.variant_id): s for s in rows}


def move(db, user, rows, branch_id, variant_id, delta, reference, reason):
    row = rows.get((branch_id, variant_id))
    before = row.quantity if row else 0
    if before + delta < 0:
        fail(f'Stock insuficiente: disponible {before}, solicitado {-delta}.', 409)
    if not row:
        row = Stock(tenant_id=db.info['tenant_id'], branch_id=branch_id,
                    variant_id=variant_id, quantity=0)
        rows[(branch_id, variant_id)] = row
        db.add(row)
    row.quantity = before + delta
    db.add(MovimientoInventario(tenant_id=db.info['tenant_id'], variant_id=variant_id,
           branch_id=branch_id, type='ENTRY' if delta > 0 else 'EXIT', quantity=abs(delta),
           reason=reason, reference_number=reference, previous_stock=before,
           new_stock=row.quantity, user_id=user.id, payment_status=None))


def price(variant):
    value = money(variant.price_override if variant.price_override is not None else variant.product.price)
    promo = variant.product.promotion
    today = now().astimezone(timezone(timedelta(hours=-4))).date()
    if promo and promo.is_active and promo.start_date <= today <= promo.end_date:
        value = money(value * (1 - Decimal(str(promo.discount_percent)) / 100))
    return value


def purchases(db, user, search=''):
    query = db.query(Pago).filter(Pago.status == 'PAID', Pago.items_detail.isnot(None))
    if user.role == 'CUSTOMER':
        query = query.filter(Pago.customer_id == user.id)
    else:
        scope = resolve_branch(user)
        if scope:
            query = query.filter(Pago.branch_id == scope)
    if search:
        query = query.filter(or_(Pago.payment_code.ilike('%' + search + '%'), Pago.customer_name.ilike('%' + search + '%')))
    result = []
    for p in query.order_by(Pago.paid_at.desc()).limit(100):
        items = json.loads(p.items_detail or '[]')
        used = {}
        for exchange in db.query(CambioPrenda).filter(CambioPrenda.payment_id == p.id):
            used[exchange.original_line] = used.get(exchange.original_line, 0) + exchange.quantity
        result.append(dict(id=p.id, code=p.payment_code, branch_id=p.branch_id,
                      customer_name=p.customer_name, currency=p.currency, amount=p.amount,
                      paid_at=p.paid_at, items=[dict(item, line=i, available_to_exchange=max(0,
                      int(item['quantity']) - used.get(i, 0))) for i, item in enumerate(items)]))
    return result


def exchange(db, user, data):
    old, attrs = start(db, user, data, CambioPrenda)
    if old:
        resolve_branch(user, old.branch_id)
        return serialize(old)
    p = db.query(Pago).filter(Pago.id == data.payment_id).with_for_update(of=Pago).populate_existing().first()
    if not p or p.status != 'PAID' or not p.paid_at:
        fail('Selecciona una compra pagada.', 404)
    resolve_branch(user, p.branch_id)
    branch(db, p.branch_id)
    if now() - aware(p.paid_at) > timedelta(days=30):
        fail('El plazo de cambios es de 30 días desde el pago.')
    items = json.loads(p.items_detail or '[]')
    if data.original_line >= len(items):
        fail('El comprobante no contiene esa línea de compra.')
    item = items[data.original_line]
    returned_id = item.get('variant_id')
    if not returned_id or returned_id == data.new_variant_id:
        fail('Elige una talla o color diferente del mismo producto.')
    used = db.query(func.coalesce(func.sum(CambioPrenda.quantity), 0)).filter(
        CambioPrenda.payment_id == p.id, CambioPrenda.original_line == data.original_line).scalar()
    if used + data.quantity > int(item['quantity']):
        fail('La cantidad supera las unidades de la compra que todavía pueden cambiarse.', 409)
    variants, rows = stocks(db, [returned_id, data.new_variant_id], [p.branch_id])
    returned, replacement = variants[returned_id], variants[data.new_variant_id]
    if returned.product_id != replacement.product_id or not replacement.is_active or not replacement.product.is_active:
        fail('La nueva variante debe estar activa y pertenecer al mismo producto.')
    paid = money(Decimal(str(item.get('subtotal', Decimal(str(item['unit_price'])) * int(item['quantity'])))) / int(item['quantity']))
    new_price = price(replacement)
    if new_price < paid:
        fail('Esta versión permite cambios de igual o mayor precio; no admite devoluciones de dinero.')
    difference = money((new_price - paid) * data.quantity)
    if difference != data.expected_difference:
        fail('El precio cambió. Actualiza la selección y revisa la diferencia antes de cobrar.', 409)
    if difference > 0 and not data.confirm_cash:
        fail('Confirma que cobraste la diferencia en efectivo.')
    move(db, user, rows, p.branch_id, data.new_variant_id, -data.quantity, attrs['id'], 'Salida por cambio de talla/color')
    move(db, user, rows, p.branch_id, returned_id, data.quantity, attrs['id'], 'Prenda devuelta apta para venta')
    receipt = Pago(id=str(uuid.uuid4()), tenant_id=p.tenant_id, payment_code='CAM-' + secrets.token_hex(5).upper(),
                   branch_id=p.branch_id, customer_id=p.customer_id, customer_name=p.customer_name,
                   customer_email=p.customer_email, concept=f'Cambio de talla/color de {p.payment_code}',
                   amount=difference, currency=p.currency, payment_type='EFECTIVO', status='PAID',
                   reference='CAMBIO:' + attrs['id'], cashier_id=user.id, paid_at=now(),
                   notes=f'{data.quantity} unidad(es). {returned.sku} → {replacement.sku}. Crédito unitario {paid}; nuevo precio {new_price}.')
    db.add(receipt)
    result = CambioPrenda(**attrs, payment_id=p.id, receipt_payment_id=receipt.id, branch_id=p.branch_id,
                         original_line=data.original_line, returned_variant_id=returned_id,
                         new_variant_id=replacement.id, quantity=data.quantity,
                         original_unit_price=paid, new_unit_price=new_price, difference=difference)
    db.add(result)
    audit(db, user, 'REGISTRO_CAMBIO_PRENDA', f'Cambio {result.id} de {p.payment_code}; diferencia {difference} {p.currency}', p.branch_id)
    db.commit()
    return serialize(result)


def send_transfer(db, user, data):
    old, attrs = start(db, user, data, TrasladoInventario)
    if old:
        resolve_branch(user, old.origin_id)
        return serialize(old)
    resolve_branch(user, data.origin_id)
    if data.origin_id == data.destination_id:
        fail('Origen y destino deben ser distintos.')
    branch(db, data.origin_id)
    branch(db, data.destination_id)
    if len({item.variant_id for item in data.items}) != len(data.items):
        fail('No repitas una variante en el lote.')
    variants, rows = stocks(db, [i.variant_id for i in data.items], [data.origin_id])
    details = []
    for item in sorted(data.items, key=lambda i: i.variant_id):
        v = variants[item.variant_id]
        if not v.is_active or not v.product.is_active:
            fail('El lote contiene una prenda inactiva.')
        move(db, user, rows, data.origin_id, v.id, -item.quantity, attrs['id'], 'Envío entre sucursales; stock en tránsito')
        details.append(dict(variant_id=v.id, quantity=item.quantity, product_name=v.product.name,
                            sku=v.sku, size=v.size.name, color=v.color.name))
    row = TrasladoInventario(**attrs, origin_id=data.origin_id, destination_id=data.destination_id,
                             status='SENT', items_json=json.dumps(details), notes=data.notes)
    db.add(row)
    audit(db, user, 'REGISTRO_ENVIO_TRASLADO', f'Traslado {row.id} hacia {data.destination_id}', data.origin_id)
    db.commit()
    return serialize(row)


def receive_transfer(db, user, transfer_id):
    row = db.query(TrasladoInventario).filter(TrasladoInventario.id == transfer_id).with_for_update().populate_existing().first()
    if not row:
        fail('Traslado no encontrado.', 404)
    resolve_branch(user, row.destination_id)
    branch(db, row.destination_id)
    if row.status == 'RECEIVED':
        return serialize(row)
    items = json.loads(row.items_json)
    _, rows = stocks(db, [i['variant_id'] for i in items], [row.destination_id])
    for item in sorted(items, key=lambda i: i['variant_id']):
        move(db, user, rows, row.destination_id, item['variant_id'], item['quantity'], row.id, 'Recepción de traslado entre sucursales')
    row.status, row.received_by, row.received_at = 'RECEIVED', user.id, now()
    audit(db, user, 'REGISTRO_RECEPCION_TRASLADO', f'Recepción completa de traslado {row.id}', row.destination_id)
    db.commit()
    return serialize(row)


def transfers(db, user):
    query = db.query(TrasladoInventario)
    scope = resolve_branch(user)
    if scope:
        query = query.filter(or_(TrasladoInventario.origin_id == scope, TrasladoInventario.destination_id == scope))
    return [serialize(row) for row in query.order_by(TrasladoInventario.created_at.desc()).limit(100)]


def balance(db, user_id):
    return int(db.query(func.coalesce(func.sum(MovimientoPuntos.points), 0)).filter(MovimientoPuntos.customer_id == user_id).scalar())


def loyalty(db, user):
    entries = db.query(MovimientoPuntos).filter(MovimientoPuntos.customer_id == user.id).order_by(MovimientoPuntos.created_at.desc()).limit(100)
    rewards = db.query(BeneficioPuntos).filter(BeneficioPuntos.customer_id == user.id).order_by(BeneficioPuntos.created_at.desc()).limit(50)
    return dict(balance=balance(db, user.id), points_per_bob=10, redeem_points=100,
                discount_percent=10, max_discount_bob=20,
                entries=[serialize(row) for row in entries], rewards=[serialize(row) for row in rewards])


def redeem(db, user, data):
    old, attrs = start(db, user, data, BeneficioPuntos)
    if old:
        return serialize(old)
    db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == user.id).with_for_update().first()
    if balance(db, user.id) < 100:
        fail('Necesitas 100 puntos disponibles para canjear este beneficio.', 409)
    row = BeneficioPuntos(**attrs, customer_id=user.id, code='VESTA-' + secrets.token_hex(5).upper(),
                         status='AVAILABLE', expires_at=now() + timedelta(days=30), discount_amount=0)
    db.add(row)
    db.add(MovimientoPuntos(tenant_id=db.info['tenant_id'], customer_id=user.id,
           source_key='redeem:' + row.id, points=-100, description='Canje: cupón 10%, máximo Bs 20, válido 30 días'))
    audit(db, user, 'REGISTRO_CANJE_PUNTOS', f'Canje de 100 puntos: {row.code}')
    db.commit()
    return serialize(row)


def apply_reward(db, user, data):
    p = db.query(Pago).filter(Pago.id == data.payment_id).with_for_update(of=Pago).populate_existing().first()
    if not p:
        fail('Cobro no encontrado.', 404)
    resolve_branch(user, p.branch_id)
    reward = db.query(BeneficioPuntos).filter(BeneficioPuntos.code == data.code).with_for_update().populate_existing().first()
    if not reward or reward.customer_id != p.customer_id:
        fail('El cupón no pertenece al cliente identificado de este cobro.', 404)
    if reward.status == 'USED' and reward.payment_id == p.id:
        return serialize(reward)
    if reward.status != 'AVAILABLE' or aware(reward.expires_at) <= now():
        fail('El cupón ya fue utilizado o venció.', 409)
    if p.status != 'PENDING' or p.paypal_order_id or p.reservation_id or p.currency != 'BOB' or not p.items_detail:
        fail('Aplica el cupón a una venta directa en BOB pendiente, antes de iniciar su pago.')
    if db.query(BeneficioPuntos).filter(BeneficioPuntos.payment_id == p.id).first():
        fail('Esta compra ya tiene un cupón.', 409)
    items = json.loads(p.items_detail)
    for item in items:
        variant = db.query(VarianteProducto).filter(VarianteProducto.id == item['variant_id']).first()
        if not variant or price(variant) < money(variant.price_override if variant.price_override is not None else variant.product.price):
            fail('El cupón no se combina con promociones activas.')
    discount = min(money(p.amount * Decimal('.10')), Decimal('20.00'))
    if discount <= 0:
        fail('El importe no permite aplicar el cupón.')
    ratio = (money(p.amount) - discount) / money(p.amount)
    for item in items:
        item['unit_price'] = float(money(Decimal(str(item['unit_price'])) * ratio))
        item['subtotal'] = float(money(Decimal(str(item['unit_price'])) * int(item['quantity'])))
    # Charge the sum of rounded unit prices; receipt and subsequent exchanges agree.
    new_amount = sum((money(i['subtotal']) for i in items), Decimal('0'))
    actual_discount = money(p.amount) - new_amount
    if actual_discount <= 0 or actual_discount > 20:
        fail('No se puede redondear el cupón para estas cantidades. Divide la venta en líneas menores.')
    p.amount, p.items_detail = new_amount, json.dumps(items)
    reward.status, reward.payment_id, reward.discount_amount = 'USED', p.id, actual_discount
    audit(db, user, 'REGISTRO_APLICAR_BENEFICIO', f'{reward.code} aplicado a {p.payment_code}: Bs {actual_discount}', p.branch_id)
    db.commit()
    return serialize(reward)


DELIVERY_FEES = {'CENTRO': Decimal('15.00'), 'PERIFERIA': Decimal('25.00')}


def delivery_create(db, user, data):
    old, attrs = start(db, user, data, EntregaDomicilio)
    if old:
        if user.role == 'CUSTOMER' and old.customer_id != user.id:
            fail('Entrega no encontrada.', 404)
        if user.role != 'CUSTOMER':
            resolve_branch(user, old.branch_id)
        return serialize(old)
    p = db.query(Pago).filter(Pago.id == data.payment_id).with_for_update(of=Pago).populate_existing().first()
    if not p or p.status != 'PAID' or p.currency != 'BOB' or not p.items_detail:
        fail('Selecciona una compra de prendas pagada en BOB.', 404)
    if user.role == 'CUSTOMER':
        if p.customer_id != user.id:
            fail('Compra no encontrada.', 404)
    else:
        resolve_branch(user, p.branch_id)
    branch(db, p.branch_id)
    if db.query(EntregaDomicilio).filter(EntregaDomicilio.payment_id == p.id).first():
        fail('Esta compra ya tiene una solicitud de entrega.', 409)
    fee = DELIVERY_FEES[data.zone]
    shipping = Pago(id=str(uuid.uuid4()), tenant_id=p.tenant_id,
                   payment_code='ENV-' + secrets.token_hex(5).upper(), branch_id=p.branch_id,
                   customer_id=p.customer_id, customer_name=p.customer_name, customer_email=p.customer_email,
                   concept=f'Envío a domicilio de {p.payment_code}', amount=fee, currency='BOB',
                   payment_type='EFECTIVO', status='PENDING', reference='DELIVERY:' + attrs['id'])
    db.add(shipping)
    row = EntregaDomicilio(**attrs, payment_id=p.id, shipping_payment_id=shipping.id,
                          customer_id=p.customer_id, branch_id=p.branch_id,
                          recipient=data.recipient, phone=data.phone, address=data.address, zone=data.zone,
                          fee=fee, status='PENDING', courier='', history_json=json.dumps([
                          dict(status='PENDING', at=now().isoformat(), note='Solicitud creada; envío pendiente de pago.')]))
    db.add(row)
    audit(db, user, 'REGISTRO_SOLICITUD_DELIVERY', f'Entrega {row.id}; tarifa Bs {fee}; cobro {shipping.payment_code}', p.branch_id)
    db.commit()
    return delivery_view(db, row)


def delivery_view(db, row):
    result = serialize(row)
    shipping = db.query(Pago).filter(Pago.id == row.shipping_payment_id).first()
    result['shipping_payment_status'] = shipping.status if shipping else None
    result['shipping_payment_code'] = shipping.payment_code if shipping else None
    return result


def deliveries(db, user):
    query = db.query(EntregaDomicilio)
    if user.role == 'CUSTOMER':
        query = query.filter(EntregaDomicilio.customer_id == user.id)
    else:
        scope = resolve_branch(user)
        if scope:
            query = query.filter(EntregaDomicilio.branch_id == scope)
    return [delivery_view(db, row) for row in query.order_by(EntregaDomicilio.created_at.desc()).limit(100)]


def delivery_status(db, user, delivery_id, data):
    row = db.query(EntregaDomicilio).filter(EntregaDomicilio.id == delivery_id).with_for_update().populate_existing().first()
    if not row:
        fail('Entrega no encontrada.', 404)
    resolve_branch(user, row.branch_id)
    if row.status == data.status:
        return delivery_view(db, row)
    allowed = {'PENDING': {'PREPARING', 'CANCELLED'}, 'PREPARING': {'OUT_FOR_DELIVERY', 'CANCELLED'},
               'OUT_FOR_DELIVERY': {'DELIVERED', 'FAILED'}, 'FAILED': {'OUT_FOR_DELIVERY'}}
    if data.status not in allowed.get(row.status, set()):
        fail('Ese cambio de estado no está permitido.', 409)
    shipping = db.query(Pago).filter(Pago.id == row.shipping_payment_id).with_for_update(of=Pago).populate_existing().first()
    if data.status != 'CANCELLED' and shipping.status != 'PAID':
        fail('Confirma el cobro del envío en Pagos antes de preparar o despachar.', 409)
    if data.status == 'CANCELLED':
        if shipping.status == 'PAID':
            fail('El envío ya está pagado. Requiere resolver su devolución antes de cancelar.', 409)
        shipping.status = 'CANCELLED'
    courier = data.courier or row.courier
    if data.status == 'OUT_FOR_DELIVERY' and not courier:
        fail('Indica el nombre del repartidor.')
    row.courier, row.status = courier, data.status
    history = json.loads(row.history_json)
    history.append(dict(status=row.status, at=now().isoformat(), note=data.note, courier=courier))
    row.history_json = json.dumps(history)
    audit(db, user, 'ACTUALIZAR_ESTADO_DELIVERY', f'Entrega {row.id}: {row.status}. {data.note}', row.branch_id)
    db.commit()
    return delivery_view(db, row)
