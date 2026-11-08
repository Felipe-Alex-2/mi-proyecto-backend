"""Personal payment history. Every query is constrained to the authenticated owner."""
import json
from app.configuracion import settings
from app.modelos.pago import Pago
from app.modelos.reserva import Reserva
from app.modelos.wallet import RecargaWallet
from app.modelos.saas import Empresa
from app.servicios.venta_mayor_service import stored_summary


def history(db, user):
    payments = db.query(Pago).filter(Pago.customer_id == user.id).all()
    names = {c.id: c.name for c in db.query(Empresa).all()}
    rows = []
    linked = {p.reservation_id for p in payments if p.reservation_id}
    for p in payments:
        shipping = (p.reservation.delivery_fee or 0) if p.reservation else 0
        rows.append(dict(**stored_summary(json.loads(p.items_detail or '[]'), p.amount-shipping), delivery_fee=shipping,
            id=p.id, source='payment', payment_code=p.payment_code, tenant_id=p.tenant_id,
            exchange_code=(p.reservation.reservation_code if p.reservation else p.payment_code)
                if p.status == 'PAID' and (p.items_detail or p.reservation_id) else None,
            company_name=names.get(p.tenant_id,''), branch_name=p.branch.name if p.branch else '',
            amount=p.amount, currency=p.currency, status=p.status, paid_at=p.paid_at,
            concept=p.concept, payment_type=p.payment_type, reference=p.reference,
            items_detail=p.items_detail, created_at=p.created_at))
    for r in db.query(Reserva).filter(Reserva.customer_id == user.id, Reserva.payment_status == 'PAID').all():
        if r.id in linked: continue
        rows.append(dict(**stored_summary(json.loads(r.receipt_items_detail or '[]'), (r.total_amount or 0)-(r.delivery_fee or 0)), delivery_fee=r.delivery_fee or 0,
            id='reservation:'+r.id, source='reservation', payment_code=r.reservation_code,
            exchange_code=r.reservation_code, tenant_id=r.tenant_id, company_name=names.get(r.tenant_id,''),
            branch_name=r.branch.name if r.branch else '', amount=r.total_amount, currency='USD' if r.payment_method=='WALLET' else settings.PAYPAL_CURRENCY,
            status='PAID', paid_at=r.paid_at, created_at=r.created_at, concept='Compra de prendas',
            payment_type=r.payment_method, reference=r.paypal_capture_id or r.paypal_order_id or r.reservation_code,
            items_detail=r.receipt_items_detail))
    for t in db.query(RecargaWallet).filter(RecargaWallet.customer_id == user.id).all():
        rows.append(dict(id='wallet:'+t.id, source='wallet_topup', payment_code='WAL-'+t.id.upper(),
            tenant_id=t.tenant_id, company_name=names.get(t.tenant_id,''), branch_name='',
            exchange_code=None, amount=t.amount, currency='USD', status=t.status, paid_at=t.paid_at,
            created_at=t.created_at, concept='Recarga de wallet', payment_type='PAYPAL',
            reference=t.capture_id or t.order_id, items_detail='[]'))
    return sorted(rows, key=lambda r: str(r['paid_at'] or r['created_at']), reverse=True)


def receipt_pdf(row):
    from app.esquemas.reporte import ReporteResponse
    from app.servicios.reporte_entrega_service import pdf
    details = [dict(concept=item.get('product_name','Prenda'), quantity=item.get('quantity'),
                    amount=item.get('subtotal'), currency=row['currency'])
               for item in json.loads(row.get('items_detail') or '[]')]
    if not details:
        details=[dict(concept=row['concept'],quantity=1,amount=str(row['amount']),currency=row['currency'])]
    elif row.get('delivery_fee'):
        details.append(dict(concept='Delivery - envio por recorrido',quantity=1,amount=str(row['delivery_fee']),currency=row['currency']))
    summary={k:str(row[k] or '') for k in ('company_name','branch_name','payment_code','paid_at',
        'payment_type','reference','amount','currency','status')}
    if row.get('exchange_code'): summary['exchange_code']=row['exchange_code']; summary['exchange_limit']='48 horas desde el pago'
    return pdf(ReporteResponse(report_type='receipt',title='Comprobante · '+row['payment_code'],
        generated_by='system',summary=summary,columns=['concept','quantity','amount','currency'],rows=details))
