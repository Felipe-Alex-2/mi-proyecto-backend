from datetime import datetime, timezone
from decimal import Decimal
import uuid
from fastapi import HTTPException
from app.modelos.wallet import CuentaWallet, RecargaWallet, MovimientoWallet
from app.modelos.usuario import Usuario
from app.servicios.paypal_service import PayPalService
from app.configuracion import settings


def require_sandbox():
    if settings.PAYPAL_BASE_URL.rstrip('/') != 'https://api-m.sandbox.paypal.com':
        raise HTTPException(503, 'La wallet requiere PayPal Sandbox configurado.')


def account(db, user):
    # The owner lock also serializes creation of a missing account.
    db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == user.id).with_for_update().first()
    row = db.query(CuentaWallet).filter(CuentaWallet.customer_id == user.id).with_for_update().populate_existing().first()
    if not row:
        row = CuentaWallet(tenant_id=db.info['tenant_id'],customer_id=user.id,balance=0)
        db.add(row); db.flush()
    return row


def view(db, user):
    row = db.query(CuentaWallet).filter(CuentaWallet.customer_id == user.id).first()
    entries = db.query(MovimientoWallet).filter(MovimientoWallet.customer_id == user.id).order_by(MovimientoWallet.created_at.desc()).limit(100).all()
    pending = db.query(RecargaWallet).filter(RecargaWallet.customer_id == user.id, RecargaWallet.status == 'PENDING').order_by(RecargaWallet.created_at.desc()).limit(30).all()
    return dict(balance=row.balance if row else 0,currency='USD',tenant_id=db.info['tenant_id'],
        entries=[dict(id=e.id,amount=e.amount,description=e.description,created_at=e.created_at) for e in entries],
        pending=[dict(id=t.id,amount=t.amount,order_id=t.order_id,approval_url=t.approval_url,request_id=t.request_id) for t in pending])


def topup(db, user, data):
    require_sandbox()
    account(db,user)
    row=db.query(RecargaWallet).filter(RecargaWallet.customer_id==user.id,RecargaWallet.request_id==str(data.request_id)).with_for_update().first()
    if row and row.amount != data.amount:
        raise HTTPException(409,'La solicitud de recarga ya tiene otro importe.')
    if not row:
        row=RecargaWallet(id=str(uuid.uuid4()),tenant_id=db.info['tenant_id'],customer_id=user.id,
            request_id=str(data.request_id),amount=data.amount,status='PENDING')
        db.add(row)
    # Persist the idempotency key before contacting the payment provider.
    db.commit()
    row=db.query(RecargaWallet).filter(RecargaWallet.id==row.id).with_for_update().populate_existing().one()
    if not row.order_id and row.status=='PENDING':
        try:
            result=PayPalService.create_order(amount=row.amount,currency='USD',description=f'Recarga wallet USD {row.amount}',
                custom_id='wallet:'+row.id,request_id=row.id)
        except Exception:
            db.rollback()
            raise HTTPException(502,'No se pudo abrir PayPal. Reintenta esta misma recarga.')
        row.order_id, row.approval_url=result['order_id'],result['approval_url']
        db.commit()
    return dict(id=row.id,amount=row.amount,status=row.status,order_id=row.order_id,approval_url=row.approval_url)


def validate_order(raw, topup, captured=False):
    # The provider order ID is stored by our own create-order call, never supplied
    # by the buyer. custom_id can be on the unit or on the capture representation.
    if not isinstance(raw,dict) or raw.get('status')=='UNKNOWN':
        raise HTTPException(502,'No se pudo consultar PayPal. Reintenta verificar la misma recarga.')
    units=raw.get('purchase_units',[])
    if raw.get('id')!=topup.order_id or len(units)!=1:
        raise HTTPException(409,'La orden PayPal no corresponde a esta recarga.')
    unit=units[0];captures=unit.get('payments',{}).get('captures',[])
    markers=[entry.get('custom_id') for entry in [unit,*captures] if entry.get('custom_id')]
    if any(marker!='wallet:'+topup.id for marker in markers):
        raise HTTPException(409,'La referencia de PayPal no corresponde a esta recarga.')
    amounts=[]
    if captured:
        if raw.get('status')!='COMPLETED' or len(captures)!=1 or captures[0].get('status')!='COMPLETED' or not captures[0].get('id'):
            raise HTTPException(409,'PayPal todavía no confirmó el cobro de la recarga.')
        amounts=[captures[0].get('amount',{})]
    else:
        if raw.get('status') not in ('CREATED','SAVED','APPROVED','COMPLETED','PAYER_ACTION_REQUIRED'):
            raise HTTPException(409,'Esta orden de PayPal no está disponible para confirmar.')
        if unit.get('amount'):amounts=[unit['amount']]
        elif captures:amounts=[c.get('amount',{}) for c in captures]
        else:raise HTTPException(409,'PayPal no devolvió el importe de la orden. Reintenta verificarla.')
    for amount in amounts:
        try:matches=amount.get('currency_code')=='USD' and Decimal(str(amount.get('value'))) == Decimal(topup.amount)
        except Exception:matches=False
        if not matches:raise HTTPException(409,'La moneda o el importe cobrado no corresponde a la recarga.')
    return captures[0]['id'] if captured else None


def capture(db,user,topup_id):
    require_sandbox()
    wallet=account(db,user)
    row=db.query(RecargaWallet).filter(RecargaWallet.id==topup_id,RecargaWallet.customer_id==user.id).with_for_update().populate_existing().first()
    if not row:
        raise HTTPException(404,'Recarga no encontrada.')
    if row.status=='PAID':
        return view(db,user)
    if not row.order_id:
        raise HTTPException(409,'Primero abre y autoriza la recarga en PayPal.')
    order=PayPalService.get_order(row.order_id)
    validate_order(order,row)
    if order.get('status')=='COMPLETED':
        capture_id=validate_order(order,row,captured=True)
    else:
        if order.get('status')!='APPROVED':
            raise HTTPException(409,'Primero aprueba el pago en PayPal y después verifica esta misma recarga.')
        try:
            result=PayPalService.capture_order(row.order_id)
        except Exception:
            raise HTTPException(502,'PayPal aún no confirmó el pago. Puedes verificarlo nuevamente.')
        raw=result.get('raw',{})
        # Some capture responses are minimal. Re-read the stored order to obtain
        # the provider's full representation before crediting any money.
        if not raw.get('purchase_units') or raw.get('status')!='COMPLETED':
            raw=PayPalService.get_order(row.order_id)
        capture_id=validate_order(raw,row,captured=True)
    from app.servicios.push_service import wallet_notification
    wallet_notification(db,user,row)
    wallet.balance=Decimal(wallet.balance)+row.amount
    row.status,row.capture_id,row.paid_at='PAID',capture_id,datetime.now(timezone.utc)
    db.add(MovimientoWallet(tenant_id=row.tenant_id,customer_id=user.id,source_key='topup:'+row.id,
        amount=row.amount,description=f'Recarga PayPal Sandbox: USD {row.amount}'))
    db.commit()
    return view(db,user)


def pay_reservation(db,user,reservation,data):
    from app.modelos.pago import Pago
    from app.modelos.movimiento_inventario import MovimientoInventario
    import json
    if reservation.customer_id!=user.id or user.role!='CUSTOMER':
        raise HTTPException(403,'Solo puedes pagar tus propias compras con la wallet.')
    if reservation.paypal_order_id:
        raise HTTPException(409,'Esta reserva ya tiene una orden PayPal. No se puede cobrar también con wallet.')
    if db.query(Pago).filter(Pago.reservation_id==reservation.id).first():
        raise HTTPException(409,'Esta reserva ya tiene un cobro en caja.')
    wallet=account(db,user)
    total=Decimal(str(reservation.total_amount))
    if total<=0 or Decimal(wallet.balance)<total:
        raise HTTPException(409,'Saldo insuficiente. Recarga tu wallet antes de pagar.')
    wallet.balance=Decimal(wallet.balance)-total
    reservation.payment_method,reservation.payment_status,reservation.status='WALLET','PAID','CONFIRMED'
    reservation.paid_at=datetime.now(timezone.utc)
    db.add(MovimientoWallet(tenant_id=reservation.tenant_id,customer_id=user.id,source_key='checkout:'+data.request_id,reservation_id=reservation.id,request_hash=checkout_hash(data),
        amount=-total,description='Compra '+reservation.reservation_code))
    lines={i['variant_id']:i for i in json.loads(reservation.receipt_items_detail)}
    from app.modelos.stock import Stock
    for item in reservation.items:
        stock=db.query(Stock).filter(Stock.branch_id==reservation.branch_id,Stock.variant_id==item.variant_id).first()
        db.add(MovimientoInventario(tenant_id=reservation.tenant_id,variant_id=item.variant_id,branch_id=reservation.branch_id,
            type='EXIT',quantity=item.quantity,reason='Compra pagada con wallet '+reservation.reservation_code,
            reference_number=reservation.reservation_code,previous_stock=stock.quantity+item.quantity,new_stock=stock.quantity,
            user_id=user.id,payment_method='WALLET',payment_status='PAID',amount=lines[item.variant_id]['subtotal']))
    # The reservation already allocated stock; settlement must not deduct it twice.


def checkout_hash(data):
    import hashlib
    delivery_fields={'fulfillment','delivery_quote_id','delivery_recipient','delivery_phone','delivery_address'}
    plain_pickup=getattr(data,'fulfillment','PICKUP')=='PICKUP' and not any(getattr(data,k,None) for k in delivery_fields-{'fulfillment'})
    # Keep the hash of existing pickup purchases stable across this schema extension.
    return hashlib.sha256(data.model_dump_json(exclude=delivery_fields if plain_pickup else set()).encode()).hexdigest()


def checkout_retry(db,user,data):
    from uuid import UUID
    from app.modelos.reserva import Reserva
    if user.role!='CUSTOMER':raise HTTPException(403,'La wallet es exclusiva del cliente propietario.')
    try:UUID(data.request_id or '')
    except (ValueError,TypeError):raise HTTPException(422,'El pago con wallet necesita un identificador de solicitud válido.')
    account(db,user)
    entry=db.query(MovimientoWallet).filter(MovimientoWallet.customer_id==user.id,MovimientoWallet.source_key=='checkout:'+data.request_id).first()
    if entry:
        if entry.request_hash!=checkout_hash(data):raise HTTPException(409,'Esta solicitud de compra ya se utilizó con otros datos.')
        reservation=db.query(Reserva).filter(Reserva.id==entry.reservation_id,Reserva.customer_id==user.id).first()
        if not reservation:raise HTTPException(409,'La compra ya fue registrada. Consulta tus comprobantes.')
        return reservation
    return None
