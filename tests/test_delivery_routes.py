import json
import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from fastapi import HTTPException
from tests.test_saas import companies, headers
from tests.test_aporte_propio import shop, stock_qty
from tests.test_wallet import mock_paypal, fund
from app.modelos import Sucursal, Reserva, Notificacion
from app.modelos.delivery import CotizacionDelivery, PedidoDelivery
from app.modelos.wallet import MovimientoWallet
from app.servicios import mapas_service
from app.servicios.saas_service import utcnow

ORIGIN='https://www.google.com/maps?q=-17.78,-63.18'
DEST='https://www.google.com/maps?q=-17.80,-63.20'


def quote(client,shop,monkeypatch):
    monkeypatch.setattr(mapas_service,'route',lambda a,b:(2500,600,'TEST_ROADS'))
    result=client.put('/api/v1/branches/'+shop['origin'],headers=headers(shop['admin']),json={'maps_url':ORIGIN})
    assert result.status_code==200,result.text
    result=client.post('/api/v1/own/deliveries/quote',headers=headers(shop['customer']),json={'branch_id':shop['origin'],'destination_maps_url':DEST})
    assert result.status_code==200,result.text
    return result.json()


def purchase(client,shop,q,method='WALLET'):
    return client.post('/api/v1/reservations',headers=headers(shop['customer']),json={
        'branch_id':shop['origin'],'payment_method':method,'request_id':str(uuid.uuid4()),
        'items':[{'variant_id':shop['variant'].id,'quantity':1}],
        'fulfillment':'DELIVERY','delivery_quote_id':q['id'],'delivery_recipient':'Cliente Delivery',
        'delivery_phone':'70001234','delivery_address':'Calle prueba 123, puerta azul'})


def test_quote_road_distance_currency_origin_and_scope(client,db_session,shop,monkeypatch):
    q=quote(client,shop,monkeypatch)
    assert q['distance_km']==2.5 and q['fee_bob']==10 and q['fee_usd']==1.44
    assert q['bob_per_usd']==6.96 and q['estimated_minutes_min']==25
    assert q['origin_maps_url']==ORIGIN and q['destination_maps_url']==DEST
    assert client.post('/api/v1/own/deliveries/quote',headers=headers(shop['customer']),json={'branch_id':shop['foreign'],'destination_maps_url':DEST}).status_code in (403,404)
    assert client.post('/api/v1/own/deliveries/quote',headers=headers(shop['admin']),json={'branch_id':shop['origin'],'destination_maps_url':DEST}).status_code==403


def test_paid_wallet_delivery_accept_dispatch_push_once_and_complete(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop)
    q=quote(client,shop,monkeypatch)
    result=purchase(client,shop,q)
    assert result.status_code==201,result.text
    r=result.json();delivery=r['delivery'];id=delivery['id']
    assert r['payment_status']=='PAID' and delivery['status']=='REQUESTED' and r['delivery_fee']==1.44
    assert r['total_amount']==51.44
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==48.56
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    auth=headers(shop['admin']);url='/api/v1/own/deliveries/'+id
    assert client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY','courier':'Repartidor'}).status_code==409
    assert client.patch(url,headers=headers(shop['other_admin']),json={'status':'ACCEPTED'}).status_code==404
    assert client.patch(url,headers=auth,json={'status':'ACCEPTED'}).status_code==200
    assert client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY'}).status_code==422
    sent=client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY','courier':'Repartidor Uno'})
    assert sent.status_code==200,sent.text
    assert sent.json()['departed_at'] and sent.json()['estimated_arrival_at']
    assert client.patch(url,headers=auth,json={'status':'OUT_FOR_DELIVERY','courier':'Repartidor Uno'}).status_code==200
    db_session.info.clear()
    assert db_session.query(Notificacion).filter_by(user_id=shop['customer'].id,notification_type='DELIVERY_OUT_FOR_DELIVERY').count()==1
    assert client.patch(url,headers=auth,json={'status':'DELIVERED'}).status_code==200
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    own=client.get('/api/v1/reservations',headers=headers(shop['customer'])).json()
    assert own[0]['delivery']['status']=='DELIVERED'


def test_rejected_delivery_keeps_garments_paid_refunds_shipping_once(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop)
    result=purchase(client,shop,quote(client,shop,monkeypatch));assert result.status_code==201,result.text
    url='/api/v1/own/deliveries/'+result.json()['delivery']['id'];auth=headers(shop['admin'])
    assert client.patch(url,headers=auth,json={'status':'REJECTED'}).status_code==422
    for _ in range(2):
        response=client.patch(url,headers=auth,json={'status':'REJECTED','note':'No hay repartidor disponible'})
        assert response.status_code==200,response.text
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==50
    db_session.info.clear();r=db_session.get(Reserva,result.json()['id'])
    assert r.payment_status=='PAID' and r.status=='CONFIRMED'
    assert db_session.query(MovimientoWallet).filter(MovimientoWallet.source_key.like('delivery-refund:%')).count()==1


@pytest.mark.parametrize('invalid',['expired','origin','cash'])
def test_invalid_delivery_rolls_back_stock_and_wallet(client,db_session,shop,monkeypatch,invalid):
    mock_paypal(monkeypatch);fund(client,shop);q=quote(client,shop,monkeypatch)
    db_session.info.clear()
    if invalid=='expired':db_session.get(CotizacionDelivery,q['id']).expires_at=utcnow()-timedelta(seconds=1)
    if invalid=='origin':db_session.get(Sucursal,shop['origin']).latitude=Decimal('-17.81')
    db_session.commit()
    result=purchase(client,shop,q,'EFECTIVO' if invalid=='cash' else 'WALLET')
    assert result.status_code in (409,422),result.text
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    assert db_session.query(Reserva).count()==0 and db_session.query(PedidoDelivery).count()==0
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==100


def test_paypal_delivery_only_visible_to_staff_after_capture(client,db_session,shop,monkeypatch):
    orders=mock_paypal(monkeypatch)
    result=purchase(client,shop,quote(client,shop,monkeypatch),'PAYPAL');assert result.status_code==201,result.text
    assert result.json()['delivery']['status']=='AWAITING_PAYMENT'
    assert client.get('/api/v1/own/deliveries',headers=headers(shop['admin'])).json()==[]
    auth=headers(shop['customer'])
    order=client.post('/api/v1/reservations/'+result.json()['id']+'/paypal-order',headers=auth)
    assert order.status_code==200,order.text
    assert orders[order.json()['order_id']]['amount']==51.44
    captured=client.post('/api/v1/reservations/paypal-capture',headers=auth,json={'order_id':order.json()['order_id']})
    assert captured.status_code==200,captured.text
    assert captured.json()['reservation']['total_amount']==51.44
    assert captured.json()['reservation']['delivery']['status']=='REQUESTED'
    assert client.get('/api/v1/own/deliveries',headers=headers(shop['admin'])).json()[0]['status']=='REQUESTED'



@pytest.mark.parametrize('link',['https://evil.example/maps?q=1,2','http://maps.google.com/?q=1,2','https://google.com:bad/maps?q=1,2','https://google.com@127.0.0.1/maps','https://goo.gl/other'])
def test_maps_rejects_untrusted_links(link):
    with pytest.raises(HTTPException) as e:mapas_service.resolve(link)
    assert e.value.status_code==422


def test_maps_pin_coordinates_precede_viewport_and_no_fake_route(monkeypatch):
    assert mapas_service.coordinates('https://www.google.com/maps/@-1,-2,12z/data=!3d-17.8!4d-63.2')==(-17.8,-63.2)
    from app.configuracion import settings
    monkeypatch.setattr(settings,'GOOGLE_MAPS_API_KEY','');monkeypatch.setattr(settings,'DELIVERY_OSRM_URL','')
    with pytest.raises(HTTPException) as e:mapas_service.route((-17.8,-63.2),(-17.9,-63.1))
    assert e.value.status_code==503


def test_google_routes_uses_road_fields_and_osrm_uses_lon_lat(monkeypatch):
    import httpx
    from app.configuracion import settings
    monkeypatch.setattr(settings,'GOOGLE_MAPS_API_KEY','test-key')
    def post(url,**kwargs):
        assert 'routes.googleapis.com' in url
        assert kwargs['json']['origin']['location']['latLng']['latitude']==-17.8
        assert kwargs['headers']['X-Goog-FieldMask']=='routes.distanceMeters,routes.duration'
        return httpx.Response(200,json={'routes':[{'distanceMeters':2500,'duration':'600s'}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    assert mapas_service.route((-17.8,-63.2),(-17.9,-63.1))==(2500,600,'GOOGLE_ROUTES')
    monkeypatch.setattr(settings,'GOOGLE_MAPS_API_KEY','')
    monkeypatch.setattr(settings,'DELIVERY_OSRM_URL','https://routes.example')
    def get(url,**kwargs):
        assert '/driving/-63.2,-17.8;-63.1,-17.9' in url
        return httpx.Response(200,json={'routes':[{'distance':2500.2,'duration':600.1}]},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx,'get',get)
    assert mapas_service.route((-17.8,-63.2),(-17.9,-63.1))==(2501,601,'OSRM')


def test_short_link_redirect_cannot_fetch_non_google_host(monkeypatch):
    import httpx
    calls=[];original=httpx.Client
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'location':'http://127.0.0.1/secret'})
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    with pytest.raises(HTTPException) as e:mapas_service.resolve('https://maps.app.goo.gl/example')
    assert e.value.status_code==422 and len(calls)==1


def test_delivery_schema_upgrades_old_tables_twice():
    from sqlalchemy import create_engine,text,inspect
    from app.nucleo.esquema_delivery import ensure_delivery_schema
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE branches (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE reservations (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text("INSERT INTO reservations VALUES ('existing')"))
    ensure_delivery_schema(engine);ensure_delivery_schema(engine)
    assert {'maps_url','latitude','longitude'}<={c['name'] for c in inspect(engine).get_columns('branches')}
    with engine.connect() as conn:assert conn.execute(text('SELECT delivery_fee FROM reservations')).scalar()==0
    engine.dispose()


def test_shipping_does_not_give_points_or_inflate_exchange_credit(client,db_session,shop,monkeypatch):
    from app.modelos.aporte_propio import MovimientoPuntos
    mock_paypal(monkeypatch);fund(client,shop)
    q=quote(client,shop,monkeypatch)
    db_session.info.clear();stored=db_session.get(CotizacionDelivery,q['id'])
    stored.fee_usd=Decimal('20');stored.fee_bob=Decimal('139.20');db_session.commit()
    bought=purchase(client,shop,q);assert bought.status_code==201,bought.text
    db_session.info.clear()
    points=db_session.query(MovimientoPuntos).filter_by(source_key='reservation:'+bought.json()['id']).one()
    assert points.points==5
    purchases=client.get('/api/v1/own/purchases?for_exchange=true',headers=headers(shop['admin']))
    assert purchases.status_code==200,purchases.text
    line=next(p for p in purchases.json() if p['id']==bought.json()['id'])['items'][0]
    assert line['subtotal']==50
    history=client.get('/api/v1/saas/history',headers=headers(shop['customer']))
    row=next(r for r in history.json() if r['id']=='reservation:'+bought.json()['id'])
    assert row['subtotal_before_wholesale']==50 and row['amount']==70 and row['delivery_fee']==20
    from app.servicios import reporte_entrega_service
    generated=[]
    monkeypatch.setattr(reporte_entrega_service,'pdf',lambda report:generated.append(report) or b'%PDF-test')
    receipt=client.get('/api/v1/saas/history/'+row['id']+'/invoice',headers=headers(shop['customer']))
    assert receipt.status_code==200,receipt.text
    assert len(generated[0].rows)==2
    assert sum(Decimal(str(r['amount'])) for r in generated[0].rows)==Decimal('70')
    assert 'Delivery' in generated[0].rows[-1]['concept']


def test_existing_pickup_wallet_hash_is_preserved():
    import hashlib
    from app.esquemas.reserva import ReservaCreate
    from app.servicios.wallet_service import checkout_hash
    data=ReservaCreate(branch_id='branch',payment_method='WALLET',items=[{'variant_id':'v','quantity':1}])
    old_json='{"request_id":null,"coupon_code":null,"branch_id":"branch","items":[{"variant_id":"v","quantity":1}],"customer_notes":null,"payment_method":"WALLET"}'
    assert checkout_hash(data)==hashlib.sha256(old_json.encode()).hexdigest()
