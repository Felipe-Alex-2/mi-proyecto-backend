import json
import math
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP
from urllib.parse import urlencode
from fastapi import HTTPException
from app.modelos.delivery import CotizacionDelivery,PedidoDelivery
from app.modelos.sucursal import Sucursal
from app.modelos.reserva import Reserva
from app.modelos.usuario import Usuario
from app.modelos.notificacion import Notificacion
from app.nucleo.ambito_sucursal import resolve_branch
from app.nucleo.transacciones import commit_or_flush
from app.servicios.saas_service import utcnow,aware
from app.servicios import mapas_service
from app.configuracion import settings


def quote_view(db,q):
    branch=db.query(Sucursal).filter(Sucursal.id==q.branch_id).first()
    minutes=math.ceil(q.duration_seconds/60)
    prep=max(0,settings.DELIVERY_PREPARATION_MINUTES)
    route_link='https://www.google.com/maps/dir/?'+urlencode({'api':1,'origin':f'{q.origin_lat},{q.origin_lon}',
        'destination':f'{q.destination_lat},{q.destination_lon}','travelmode':'driving'})
    return dict(id=q.id,branch_id=q.branch_id,branch_name=branch.name if branch else '',
        origin_maps_url=q.origin_maps_url,destination_maps_url=q.destination_maps_url,
        origin_lat=float(q.origin_lat),origin_lon=float(q.origin_lon),destination_lat=float(q.destination_lat),destination_lon=float(q.destination_lon),
        distance_meters=q.distance_meters,distance_km=round(q.distance_meters/1000,3),duration_minutes=minutes,
        estimated_minutes_min=prep+minutes,estimated_minutes_max=prep+minutes+10,
        fee_usd=float(q.fee_usd),fee_bob=float(q.fee_bob),bob_per_usd=float(q.bob_per_usd),currency='USD',rate_bob_per_km=4,provider=q.provider,expires_at=q.expires_at,
        directions_url=route_link,estimate_note='Estimado desde la aceptación: incluye preparación y recorrido; puede variar por tráfico y disponibilidad.')


def quote(db,user,data):
    if user.role!='CUSTOMER':raise HTTPException(403,'La cotización corresponde al cliente que hará la compra.')
    if db.info.get('customer_branch_id') and data.branch_id!=db.info['customer_branch_id']:
        raise HTTPException(403,'Selecciona la sucursal de tu compra para cotizar el envío.')
    branch=db.query(Sucursal).filter(Sucursal.id==data.branch_id,Sucursal.is_active==True).first()
    if not branch:raise HTTPException(404,'Sucursal no encontrada.')
    if not branch.maps_url or branch.latitude is None or branch.longitude is None:
        raise HTTPException(409,'La sucursal debe guardar su ubicación de Google Maps antes de ofrecer delivery.')
    link=mapas_service.validate_link(data.destination_maps_url)
    existing=db.query(CotizacionDelivery).filter(CotizacionDelivery.customer_id==user.id,
        CotizacionDelivery.branch_id==branch.id,CotizacionDelivery.destination_maps_url==link,
        CotizacionDelivery.origin_maps_url==branch.maps_url,CotizacionDelivery.origin_lat==branch.latitude,CotizacionDelivery.origin_lon==branch.longitude,~CotizacionDelivery.id.in_(db.query(PedidoDelivery.quote_id)),CotizacionDelivery.expires_at>utcnow()).order_by(CotizacionDelivery.created_at.desc()).first()
    if existing:return quote_view(db,existing)
    destination=mapas_service.resolve(link)
    distance,duration,provider=mapas_service.route((float(branch.latitude),float(branch.longitude)),destination)
    fee=(Decimal(distance)*Decimal('4')/Decimal('1000')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    rate=Decimal(str(settings.DELIVERY_BOB_PER_USD))
    if not rate.is_finite() or rate<=0:raise HTTPException(503,'Configura el tipo de cambio para el delivery.')
    fee_usd=(fee/rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    if fee>Decimal('99999999.99'):raise HTTPException(422,'La distancia supera el importe admitido para un envío.')
    row=CotizacionDelivery(tenant_id=db.info['tenant_id'],customer_id=user.id,branch_id=branch.id,
        origin_maps_url=branch.maps_url,destination_maps_url=link,origin_lat=branch.latitude,origin_lon=branch.longitude,
        destination_lat=destination[0],destination_lon=destination[1],distance_meters=distance,duration_seconds=duration,
        fee_bob=fee,fee_usd=fee_usd,bob_per_usd=rate,provider=provider,expires_at=utcnow()+timedelta(minutes=10))
    db.add(row);commit_or_flush(db)
    return quote_view(db,row)


def order_view(db,row):
    q=db.query(CotizacionDelivery).filter(CotizacionDelivery.id==row.quote_id).first()
    r=db.query(Reserva).filter(Reserva.id==row.reservation_id).first()
    details=quote_view(db,q)
    return dict(details,id=row.id,source='reservation',reservation_id=row.reservation_id,reservation_code=r.reservation_code,
        recipient=row.recipient,phone=row.phone,address=row.address,status=row.status,courier=row.courier,
        fee=float(q.fee_usd),pickup_available=row.status=='REJECTED',zone='DISTANCE',created_at=row.created_at,departed_at=row.departed_at,
        estimated_arrival_at=row.estimated_arrival_at,history=json.loads(row.history_json),
        purchase_payment_status=r.payment_status,purchase_payment_method=r.payment_method)


def for_reservation(db,reservation):
    row=db.query(PedidoDelivery).filter(PedidoDelivery.reservation_id==reservation.id).first()
    return order_view(db,row) if row else None


def notify(db,row,kind,title,message,staff=False):
    if staff:
        recipients=db.query(Usuario).filter(Usuario.is_active==True,Usuario.tenant_id==row.tenant_id,
            Usuario.role.in_(['ADMIN','STORE_MANAGER','CASHIER'])).all()
        recipients=[u.id for u in recipients if u.role=='ADMIN' or u.branch_id==row.branch_id]
    else:recipients=[row.customer_id]
    for id in recipients:
        n=Notificacion(user_id=id,reservation_id=row.reservation_id,title=title,message=message,
            notification_type=kind,is_read=False)
        n._push_tenant_id=row.tenant_id;n._push_branch_id=row.branch_id
        db.add(n)


def payment_confirmed(db,reservation):
    row=db.query(PedidoDelivery).filter(PedidoDelivery.reservation_id==reservation.id).with_for_update().first()
    if not row or row.status!='AWAITING_PAYMENT' or reservation.payment_status!='PAID':return
    row.status='REQUESTED';row.updated_at=utcnow()
    history=json.loads(row.history_json);history.append(dict(status='REQUESTED',at=utcnow().isoformat(),note='Compra pagada. Solicitud pendiente de aceptación.'))
    row.history_json=json.dumps(history)
    notify(db,row,'DELIVERY_PAYMENT_CONFIRMED','Solicitud de delivery enviada','Tu compra y envío están pagados. La sucursal debe aceptar la entrega.')
    notify(db,row,'DELIVERY_REQUESTED','Nuevo delivery por aceptar',f'El pedido {reservation.reservation_code} solicita delivery. Revisa su ruta y acepta o rechaza el envío.',staff=True)


def attach(db,user,reservation,data):
    if data.fulfillment!='DELIVERY':
        if data.delivery_quote_id:raise HTTPException(422,'Selecciona delivery para usar la cotización.')
        return
    if user.role!='CUSTOMER' or data.payment_method not in ('WALLET','PAYPAL'):
        raise HTTPException(422,'El delivery requiere pago con wallet o PayPal y conexión a Internet.')
    q=db.query(CotizacionDelivery).filter(CotizacionDelivery.id==data.delivery_quote_id,
        CotizacionDelivery.customer_id==user.id,CotizacionDelivery.branch_id==reservation.branch_id).with_for_update().first()
    if not q:raise HTTPException(404,'Cotiza el envío para esta sucursal y este cliente.')
    branch=db.query(Sucursal).filter(Sucursal.id==q.branch_id).one()
    if aware(q.expires_at)<=utcnow() or branch.maps_url!=q.origin_maps_url or branch.latitude!=q.origin_lat or branch.longitude!=q.origin_lon:
        raise HTTPException(409,'La cotización venció o cambió el origen. Vuelve a calcular el envío.')
    if db.query(PedidoDelivery).filter(PedidoDelivery.quote_id==q.id).first():
        raise HTTPException(409,'Esta cotización ya se usó. Solicita una nueva.')
    recipient=(data.delivery_recipient or user.full_name or '').strip()
    phone=(data.delivery_phone or user.phone or '').strip()
    address=(data.delivery_address or '').strip()
    if len(recipient)<2 or len(phone)<7 or len(address)<5:
        raise HTTPException(422,'Completa nombre, celular y dirección con referencias para el delivery.')
    reservation.delivery_fee=q.fee_usd
    reservation.total_amount=Decimal(str(reservation.total_amount))+q.fee_usd
    row=PedidoDelivery(tenant_id=reservation.tenant_id,reservation_id=reservation.id,quote_id=q.id,
        customer_id=user.id,branch_id=reservation.branch_id,recipient=recipient,phone=phone,address=address,
        status='AWAITING_PAYMENT',history_json=json.dumps([dict(status='AWAITING_PAYMENT',at=utcnow().isoformat(),note='Pendiente de confirmar el pago de prendas y envío.')]))
    db.add(row);db.flush()


def list_orders(db,user):
    query=db.query(PedidoDelivery)
    if user.role=='CUSTOMER':query=query.filter(PedidoDelivery.customer_id==user.id)
    else:
        scope=resolve_branch(user)
        if scope:query=query.filter(PedidoDelivery.branch_id==scope)
        query=query.filter(PedidoDelivery.status!='AWAITING_PAYMENT')
    return [order_view(db,r) for r in query.order_by(PedidoDelivery.created_at.desc()).limit(100)]


def change_status(db,user,id,data):
    row=db.query(PedidoDelivery).filter(PedidoDelivery.id==id).with_for_update().populate_existing().first()
    if not row:return None
    resolve_branch(user,row.branch_id)
    if row.status==data.status:return order_view(db,row)
    allowed={'REQUESTED':{'ACCEPTED','REJECTED'},'ACCEPTED':{'OUT_FOR_DELIVERY','REJECTED'},
        'OUT_FOR_DELIVERY':{'DELIVERED','FAILED'},'FAILED':{'OUT_FOR_DELIVERY'}}
    if data.status not in allowed.get(row.status,set()):raise HTTPException(409,'Ese cambio de estado no está permitido.')
    reservation=db.query(Reserva).filter(Reserva.id==row.reservation_id).with_for_update(of=Reserva).one()
    if reservation.payment_status!='PAID':raise HTTPException(409,'La compra debe estar pagada antes de gestionar el envío.')
    courier=data.courier or row.courier
    if data.status=='OUT_FOR_DELIVERY' and not courier.strip():raise HTTPException(422,'Indica el repartidor antes de confirmar la salida.')
    if data.status=='REJECTED':
        if len(data.note.strip())<5:raise HTTPException(422,'Indica el motivo del rechazo.')
        # Keep the paid garments for pickup; return the unused delivery fee as wallet credit.
        from app.servicios.wallet_service import account
        from app.modelos.wallet import MovimientoWallet
        customer=db.query(Usuario).filter(Usuario.id==row.customer_id).one()
        wallet=account(db,customer)
        q=db.query(CotizacionDelivery).filter(CotizacionDelivery.id==row.quote_id).one()
        wallet.balance=Decimal(wallet.balance)+q.fee_usd
        db.add(MovimientoWallet(tenant_id=row.tenant_id,customer_id=row.customer_id,source_key='delivery-refund:'+row.id,
            amount=q.fee_usd,description='Envío rechazado: devolución a wallet '+reservation.reservation_code))
    if data.status=='OUT_FOR_DELIVERY':
        q=db.query(CotizacionDelivery).filter(CotizacionDelivery.id==row.quote_id).one()
        row.departed_at=utcnow();row.estimated_arrival_at=utcnow()+timedelta(seconds=q.duration_seconds)
    if data.status=='DELIVERED':
        reservation.status='COMPLETED';reservation.updated_at=utcnow();reservation.staff_user_id=user.id
        reservation.staff_notes='Entrega de delivery confirmada.'
    row.status=data.status;row.courier=courier;row.updated_at=utcnow()
    history=json.loads(row.history_json);history.append(dict(status=row.status,at=utcnow().isoformat(),note=data.note,courier=courier));row.history_json=json.dumps(history)
    messages={'ACCEPTED':('Delivery aceptado','La sucursal está preparando tu pedido.'),
        'REJECTED':('Pedido disponible para recoger','El delivery fue rechazado. Tus prendas siguen pagadas para recoger y el envío se devolvió a tu wallet. '+data.note),
        'OUT_FOR_DELIVERY':('Tu delivery salió','Tu pedido está en camino. Revisa el seguimiento en Reservas.'),
        'DELIVERED':('Delivery entregado','La sucursal confirmó la entrega de tu pedido.'),
        'FAILED':('No se pudo entregar','Revisa Reservas y comunícate con la sucursal. '+data.note)}
    title,message=messages[data.status];notify(db,row,'DELIVERY_'+data.status,title,message)
    from app.servicios.aporte_propio_service import audit
    audit(db,user,'ACTUALIZAR_ESTADO_DELIVERY',f'Pedido {row.id}: {row.status}. {data.note}',row.branch_id)
    commit_or_flush(db)
    return order_view(db,row)
