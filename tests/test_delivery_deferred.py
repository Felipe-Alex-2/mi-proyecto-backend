import uuid
from decimal import Decimal
import pytest
from tests.test_saas import companies,headers
from tests.test_aporte_propio import shop,stock_qty
from tests.test_wallet import mock_paypal,fund
from app.servicios import mapas_service
from app.modelos import Reserva,Notificacion,Pago
from app.modelos.delivery import PedidoDelivery,CotizacionDelivery
from app.modelos.wallet import MovimientoWallet

LINK='https://maps.app.goo.gl/cXzSxikcRGXvG7cU8'


def order(client,shop,method='WALLET',**extra):
    return client.post('/api/v1/reservations',headers=headers(shop['customer']),json=dict(
        request_id=str(uuid.uuid4()),branch_id=shop['origin'],payment_method=method,
        items=[dict(variant_id=shop['variant'].id,quantity=1)],fulfillment='DELIVERY',
        delivery_maps_url=LINK,delivery_recipient='Felipe Cliente',delivery_phone='70001234',
        delivery_address='Calle 123, puerta azul',**extra))


def maps_ready(client,shop,monkeypatch):
    result=client.put('/api/v1/branches/'+shop['origin'],headers=headers(shop['admin']),json={
        'maps_url':'https://www.google.com/maps?q=-17.78,-63.18'})
    assert result.status_code==200,result.text
    monkeypatch.setattr(mapas_service,'resolve',lambda link:(-17.757663,-63.178484))
    monkeypatch.setattr(mapas_service,'route',lambda a,b:(2500,600,'TEST_ROADS'))


def test_request_without_quote_or_branch_pin_only_pays_garments(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop)
    def no_network(*args):raise AssertionError('Do not route or resolve a request before departure')
    monkeypatch.setattr(mapas_service,'resolve',no_network);monkeypatch.setattr(mapas_service,'route',no_network)
    result=order(client,shop);assert result.status_code==201,result.text
    r=result.json();assert r['total_amount']==50 and r['delivery_fee']==0
    assert r['delivery']['status']=='REQUESTED' and r['delivery']['fee'] is None
    assert r['delivery']['fee_collection']=='CASH_ON_DELIVERY' and r['delivery']['destination_maps_url']==LINK
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==50
    db_session.info.clear();assert db_session.query(CotizacionDelivery).count()==0
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    path='/api/v1/own/deliveries/'+r['delivery']['id']
    accepted=client.patch(path,headers=headers(shop['admin']),json={'status':'ACCEPTED'})
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['status']=='ACCEPTED' and accepted.json()['fee'] is None


def test_dispatch_calculates_and_notifies_once_and_cash_is_recorded_at_delivery(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop)
    created=order(client,shop).json();id=created['delivery']['id'];url='/api/v1/own/deliveries/'+id;auth=headers(shop['admin'])
    assert client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY','courier':'Moto Uno'}).status_code==409
    assert client.patch(url,headers=auth,json={'status':'ACCEPTED'}).status_code==200
    maps_ready(client,shop,monkeypatch)
    for _ in range(2):
        sent=client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY','courier':'Moto Uno'})
        assert sent.status_code==200,sent.text
    data=sent.json();assert data['fee_usd']==1.44 and data['shipping_payment_status']=='PENDING'
    assert data['departed_at'] and data['estimated_arrival_at']
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==50
    db_session.info.clear();r=db_session.get(Reserva,created['id']);assert r.total_amount==50 and r.delivery_fee==0
    payments=db_session.query(Pago).filter_by(reference='DELIVERY:'+id).all()
    assert len(payments)==1 and payments[0].amount==Decimal('1.44') and payments[0].status=='PENDING'
    assert db_session.query(Notificacion).filter_by(user_id=shop['customer'].id,notification_type='DELIVERY_OUT_FOR_DELIVERY').count()==1
    assert client.patch(url,headers=auth,json={'status':'DELIVERED'}).status_code==422
    for _ in range(2):
        delivered=client.patch(url,headers=auth,json={'status':'DELIVERED','confirm_fee_collected':True})
        assert delivered.status_code==200,delivered.text
    assert delivered.json()['shipping_payment_status']=='PAID'
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4


def test_departure_is_not_blocked_by_missing_maps_and_web_can_retry_later(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop)
    created=order(client,shop).json();url='/api/v1/own/deliveries/'+created['delivery']['id'];auth=headers(shop['admin'])
    assert client.post(url+'/calculate',headers=auth).status_code==409
    assert client.patch(url,headers=auth,json={'status':'ACCEPTED'}).status_code==200
    sent=client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY','courier':'Moto Uno'})
    assert sent.status_code==200,sent.text
    assert sent.json()['status']=='OUT_FOR_DELIVERY' and sent.json()['fee'] is None and sent.json()['route_error']
    maps_ready(client,shop,monkeypatch)
    assert client.post(url+'/calculate',headers=headers(shop['customer'])).status_code==403
    assert client.post(url+'/calculate',headers=headers(shop['other_admin'])).status_code==404
    for _ in range(2):
        result=client.post(url+'/calculate',headers=auth);assert result.status_code==200,result.text
    assert result.json()['fee_usd']==1.44 and result.json()['route_error'] is None
    db_session.info.clear()
    assert db_session.query(Pago).filter(Pago.reference.like('DELIVERY:%')).count()==1
    assert db_session.query(Notificacion).filter_by(user_id=shop['customer'].id,notification_type='DELIVERY_OUT_FOR_DELIVERY').count()==1


def test_rejection_of_unquoted_request_keeps_paid_garments_without_fake_refund(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop)
    created=order(client,shop).json();url='/api/v1/own/deliveries/'+created['delivery']['id'];auth=headers(shop['admin'])
    rejected=client.patch(url,headers=auth,json={'status':'REJECTED','note':'No hay repartidor disponible'})
    assert rejected.status_code==200,rejected.text
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==50
    db_session.info.clear()
    assert db_session.query(MovimientoWallet).filter(MovimientoWallet.source_key.like('delivery-refund:%')).count()==0
    assert db_session.get(Reserva,created['id']).payment_status=='PAID'


def test_paypal_order_only_charges_garments_and_request_appears_after_capture(client,db_session,shop,monkeypatch):
    orders=mock_paypal(monkeypatch);auth=headers(shop['customer'])
    created=order(client,shop,method='PAYPAL');assert created.status_code==201,created.text
    assert created.json()['delivery']['status']=='AWAITING_PAYMENT'
    result=client.post('/api/v1/reservations/'+created.json()['id']+'/paypal-order',headers=auth)
    assert result.status_code==200,result.text
    id=result.json()['order_id'];assert orders[id]['amount']==50
    captured=client.post('/api/v1/reservations/paypal-capture',headers=auth,json={'order_id':id})
    assert captured.status_code==200,captured.text
    assert captured.json()['reservation']['delivery']['status']=='REQUESTED'
    assert captured.json()['reservation']['total_amount']==50


def test_existing_delivery_schema_can_drop_quote_requirement_and_preserve_data():
    from sqlalchemy import create_engine,text,inspect
    from app.nucleo.esquema_delivery import ensure_delivery_schema
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE branches(id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE reservations(id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE delivery_orders(id VARCHAR(36) PRIMARY KEY,quote_id VARCHAR(36) NOT NULL)'))
        conn.execute(text("INSERT INTO delivery_orders VALUES ('old','quote')"))
    ensure_delivery_schema(engine);ensure_delivery_schema(engine)
    columns={c['name']:c for c in inspect(engine).get_columns('delivery_orders')}
    assert columns['quote_id']['nullable'] and 'destination_maps_url' in columns
    with engine.connect() as conn:assert conn.execute(text('SELECT quote_id FROM delivery_orders')).scalar()=='quote'
    engine.dispose()
