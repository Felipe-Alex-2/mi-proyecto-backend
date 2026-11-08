import json
import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from app.modelos import Pago, Reserva, Producto, VarianteProducto, Stock
from app.servicios.aporte_propio_service import now
from app.servicios.paypal_service import PayPalService
from tests.test_aporte_propio import shop, paid, stock_qty
from tests.test_saas import companies, headers


@pytest.mark.parametrize('method', ['EFECTIVO', 'PAYPAL'])
def test_mobile_reservation_code_finds_customer_and_exchanges_another_product(client, db_session, shop, monkeypatch, method):
    customer_auth, staff_auth = headers(shop['customer']), headers(shop['admin'])
    response = client.post('/api/v1/reservations', headers=customer_auth, json={
        'branch_id':shop['origin'], 'payment_method':method,
        'items':[{'variant_id':shop['variant'].id,'quantity':1}]})
    assert response.status_code == 201, response.text
    reservation = response.json()
    assert reservation['exchange_code'] is None
    rid = reservation['id']
    db_session.info.clear()
    frozen = db_session.get(Reserva, rid).receipt_items_detail
    assert json.loads(frozen)[0]['unit_price'] == 50
    if method == 'EFECTIVO':
        response = client.patch('/api/v1/reservations/'+rid+'/status', headers=staff_auth, json={
            'status':'COMPLETED','payment_status':'PAID','payment_method':'EFECTIVO','staff_notes':'Cobro confirmado en caja'})
        assert response.status_code == 200, response.text
        reservation = response.json()
    else:
        order_id = 'ORDER-TEST-'+uuid.uuid4().hex[:8]
        monkeypatch.setattr(PayPalService, 'create_order', staticmethod(lambda **kwargs: {
            'order_id':order_id,'approval_url':'https://www.sandbox.paypal.com/approve'}))
        monkeypatch.setattr(PayPalService, 'capture_order', staticmethod(lambda order: {
            'status':'COMPLETED','capture_id':'CAPTURE-TEST'}))
        response = client.post('/api/v1/reservations/'+rid+'/paypal-order', headers=customer_auth)
        assert response.status_code == 200, response.text
        response = client.post('/api/v1/reservations/paypal-capture', headers=customer_auth,json={'order_id':order_id})
        assert response.status_code == 200, response.text
        reservation = response.json()['reservation']
    assert reservation['exchange_code'] == reservation['reservation_code']
    assert reservation['receipt_issued_at'] and reservation['exchange_deadline']
    # Opening the receipt again keeps the same timestamp and code.
    response = client.get('/api/v1/reservations/'+rid, headers=customer_auth)
    assert response.status_code == 200, response.text
    assert response.json()['receipt_issued_at'] == reservation['receipt_issued_at']
    code = 'REC-'+reservation['exchange_code']
    response = client.get('/api/v1/own/purchases', headers=staff_auth, params={'search':code.lower(),'for_exchange':True})
    assert response.status_code == 200, response.text
    sale = response.json()[0]
    assert sale['customer_name'] == shop['customer'].full_name
    assert sale['customer_email'] == shop['customer'].email
    assert sale['reservation_id'] == rid and sale['source'] == 'reservation'
    db_session.info.clear()
    assert db_session.query(Pago).filter(Pago.reservation_id==rid).count() == 0
    # A distinct catalog product is eligible, and changing its old product's price
    # does not alter the actual amount originally paid.
    shop['product'].price = 500
    other = Producto(tenant_id=shop['tenant'],name='Otra prenda',price=90,category_id=shop['product'].category_id)
    db_session.add(other);db_session.flush()
    variant = VarianteProducto(tenant_id=shop['tenant'],product_id=other.id,
        size_id=shop['variant'].size_id,color_id=shop['variant'].color_id,sku='OTHER-CATALOG')
    db_session.add(variant);db_session.flush()
    db_session.add(Stock(tenant_id=shop['tenant'],branch_id=shop['origin'],variant_id=variant.id,quantity=2))
    db_session.commit()
    response=client.post('/api/v1/own/exchanges',headers=staff_auth,json={
        'request_id':str(uuid.uuid4()),'reservation_id':rid,'original_line':0,
        'new_variant_id':variant.id,'quantity':1,'resellable':True,'confirm_cash':True,'expected_difference':40})
    assert response.status_code==201,response.text
    assert Decimal(str(response.json()['difference']))==40
    assert response.json()['reservation_id']==rid
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    assert stock_qty(db_session,shop['origin'],variant.id)==1


def test_receipt_48_hour_limit_is_exact_and_checked_again_at_confirmation(client,db_session,shop,monkeypatch):
    from app.servicios import aporte_propio_service as service
    p=paid(db_session,shop)
    issued=p.paid_at
    auth=headers(shop['admin'])
    # Use a real PAY prefix, as printed on a direct-sale receipt.
    db_session.info.clear();p.payment_code='PAY-48H-TEST';db_session.commit()
    monkeypatch.setattr(service,'now',lambda:issued+timedelta(hours=48))
    response=client.get('/api/v1/own/purchases',headers=auth,params={'for_exchange':True,'search':'FAC-PAY-48H-TEST'})
    assert response.status_code==200,response.text
    assert response.json()[0]['customer_name']=='Cliente Aporte'
    monkeypatch.setattr(service,'now',lambda:issued+timedelta(hours=48,microseconds=1))
    response=client.get('/api/v1/own/purchases',headers=auth,params={'for_exchange':True,'search':'PAY-48H-TEST'})
    assert response.status_code==409 and '48 horas' in response.json()['detail']
    response=client.post('/api/v1/own/exchanges',headers=auth,json={
        'request_id':str(uuid.uuid4()),'payment_id':p.id,'original_line':0,
        'new_variant_id':shop['replacement'].id,'quantity':1,'resellable':True,'confirm_cash':True,'expected_difference':20})
    assert response.status_code==409 and '48 horas' in response.json()['detail']
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    assert stock_qty(db_session,shop['origin'],shop['replacement'].id)==3


def test_legacy_paid_reservation_uses_receipt_total_not_current_catalog_price(client,db_session,shop):
    from app.modelos.reserva_item import ReservaItem
    db_session.info.clear()
    r=Reserva(tenant_id=shop['tenant'],reservation_code='RSV-LEGACY',customer_id=shop['customer'].id,
        branch_id=shop['origin'],payment_status='PAID',payment_method='PAYPAL',status='CONFIRMED',
        total_amount=75,paid_at=now(),expires_at=now()+timedelta(days=1))
    db_session.add(r);db_session.flush()
    db_session.add(ReservaItem(tenant_id=shop['tenant'],reservation_id=r.id,variant_id=shop['variant'].id,quantity=1))
    shop['product'].price=999;db_session.commit()
    response=client.get('/api/v1/own/purchases',headers=headers(shop['admin']),params={'for_exchange':True,'search':'REC-RSV-LEGACY'})
    assert response.status_code==200,response.text
    assert response.json()[0]['items'][0]['unit_price']==75
    assert client.get('/api/v1/own/purchases',headers=headers(shop['other_admin']),params={'for_exchange':True,'search':'RSV-LEGACY'}).status_code==404
