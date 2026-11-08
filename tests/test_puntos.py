import json
import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from tests.test_aporte_propio import shop, paid, stock_qty
from tests.test_saas import companies, headers
from app.modelos import Pago, Stock
from app.modelos.aporte_propio import BeneficioPuntos, MovimientoPuntos
from app.servicios.aporte_propio_service import now


def redeem(client, shop, reward):
    response=client.post('/api/v1/own/loyalty/redeem',headers=headers(shop['customer']),json={
        'request_id':str(uuid.uuid4()),'reward':reward})
    assert response.status_code==201,response.text
    return response.json()


@pytest.mark.parametrize('kind,cost,percent',[('COUPON_7',5,7),('COUPON_10',7,10),('COUPON_15',10,15),('MYSTERY',10,0)])
def test_tiers_private_codes_and_ranking(client,db_session,shop,kind,cost,percent):
    paid(db_session,shop,200,currency='USD')
    reward=redeem(client,shop,kind)
    assert reward['points_cost']==cost and reward['discount_percent']==percent
    assert reward['max_discount'] is None
    account=client.get('/api/v1/own/loyalty',headers=headers(shop['customer'])).json()
    assert account['balance']==20-cost
    ranking=client.get('/api/v1/own/loyalty/ranking',headers=headers(shop['admin']))
    assert ranking.status_code==200,ranking.text
    assert ranking.json()[0]['points']==20-cost
    assert reward['code'] not in ranking.text and 'code' not in ranking.text
    assert client.get('/api/v1/own/loyalty/ranking',headers=headers(shop['customer'])).status_code==403
    assert client.get('/api/v1/own/loyalty/ranking',headers=headers(shop['other_admin'])).json()==[]


def test_insufficient_and_idempotent_mystery_pickup(client,db_session,shop):
    customer=headers(shop['customer']);admin=headers(shop['admin'])
    payload={'request_id':str(uuid.uuid4()),'reward':'MYSTERY'}
    assert client.post('/api/v1/own/loyalty/redeem',headers=customer,json=payload).status_code==409
    paid(db_session,shop,100,currency='USD')
    first=client.post('/api/v1/own/loyalty/redeem',headers=customer,json=payload)
    assert first.status_code==201,first.text
    assert client.post('/api/v1/own/loyalty/redeem',headers=customer,json=payload).json()['id']==first.json()['id']
    data={'code':first.json()['code'],'branch_id':shop['origin'],'variant_id':shop['variant'].id}
    assert client.post('/api/v1/own/loyalty/claim',headers=customer,json=data).status_code==403
    assert client.post('/api/v1/own/loyalty/claim',headers=headers(shop['other_admin']),json=data).status_code in (403,404)
    result=client.post('/api/v1/own/loyalty/claim',headers=admin,json=data)
    assert result.status_code==200,result.text
    assert client.post('/api/v1/own/loyalty/claim',headers=admin,json=data).status_code==200
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    assert client.get('/api/v1/own/loyalty',headers=customer).json()['balance']==0


def test_coupon_quote_atomic_checkout_settlement_and_net_points(client,db_session,shop):
    paid(db_session,shop,100,currency='USD')
    reward=redeem(client,shop,'COUPON_15')
    customer=headers(shop['customer']);admin=headers(shop['admin'])
    quote={'code':reward['code'],'branch_id':shop['origin'],'items':[{'variant_id':shop['variant'].id,'quantity':3}]}
    result=client.post('/api/v1/own/loyalty/quote',headers=customer,json=quote)
    assert result.status_code==200,result.text
    assert float(result.json()['total_amount'])==127.5
    assert client.get('/api/v1/own/loyalty',headers=customer).json()['rewards'][0]['status']=='AVAILABLE'
    sale=dict(branch_id=shop['origin'],customer_name='Cliente Aporte',customer_email=shop['customer'].email,
        concept='Venta con cupón',amount=999,currency='USD',coupon_code=reward['code'],
        items=[dict(variant_id=shop['variant'].id,quantity=3,unit_price=999)])
    response=client.post('/api/v1/payments',headers=admin,json=sale)
    assert response.status_code==201,response.text
    payment=response.json()
    assert payment['amount']==127.5
    assert client.post('/api/v1/payments',headers=admin,json=sale).status_code==409
    assert client.get('/api/v1/own/loyalty',headers=customer).json()['rewards'][0]['status']=='RESERVED'
    result=client.post('/api/v1/payments/'+payment['id']+'/cash',headers=admin,json={})
    assert result.status_code==200,result.text
    account=client.get('/api/v1/own/loyalty',headers=customer).json()
    assert account['rewards'][0]['status']=='USED' and account['balance']==12
    assert client.post('/api/v1/payments/'+payment['id']+'/cash',headers=admin,json={}).status_code==200
    assert client.get('/api/v1/own/loyalty',headers=customer).json()['balance']==12


def test_mobile_reservation_coupon_paid_and_cancellation_release(client,db_session,shop):
    paid(db_session,shop,200,currency='USD')
    reward=redeem(client,shop,'COUPON_7')
    customer=headers(shop['customer']);admin=headers(shop['admin'])
    body={'branch_id':shop['origin'],'coupon_code':reward['code'],'items':[{'variant_id':shop['variant'].id,'quantity':1}]}
    result=client.post('/api/v1/reservations',headers=customer,json=body)
    assert result.status_code==201,result.text
    reservation=result.json()
    assert reservation['total_amount']==46.5
    from app.modelos.reserva import Reserva
    db_session.info.clear()
    r=db_session.get(Reserva,reservation['id']);r.status='CANCELLED';db_session.commit()
    assert client.get('/api/v1/own/loyalty',headers=customer).json()['rewards'][0]['status']=='AVAILABLE'
    result=client.post('/api/v1/reservations',headers=customer,json=body)
    assert result.status_code==201,result.text
    db_session.info.clear()
    r=db_session.get(Reserva,result.json()['id']);r.payment_status='PAID';r.paid_at=now();db_session.commit()
    account=client.get('/api/v1/own/loyalty',headers=customer).json()
    assert account['rewards'][0]['status']=='USED' and account['balance']==19
    # No synthetic payment is created for mobile settlement.
    db_session.info.clear()
    assert db_session.query(Pago).filter(Pago.reservation_id==r.id).count()==0


def test_expired_wrong_owner_and_wholesale_coupon_rejected(client,db_session,shop):
    paid(db_session,shop,200,currency='USD')
    reward=redeem(client,shop,'COUPON_10');customer=headers(shop['customer'])
    body={'code':reward['code'],'branch_id':shop['origin'],'items':[{'variant_id':shop['variant'].id,'quantity':13}]}
    db_session.info.clear();db_session.query(Stock).filter_by(branch_id=shop['origin'],variant_id=shop['variant'].id).one().quantity=30;db_session.commit()
    result=client.post('/api/v1/own/loyalty/quote',headers=customer,json=body)
    assert result.status_code==422 and 'mayor' in result.text
    body['items'][0]['quantity']=1
    body['customer_email']='nadie@example.com'
    assert client.post('/api/v1/own/loyalty/quote',headers=headers(shop['admin']),json=body).status_code==404
    db_session.info.clear();db_session.get(BeneficioPuntos,reward['id']).expires_at=now()-timedelta(seconds=1);db_session.commit()
    assert client.post('/api/v1/own/loyalty/quote',headers=customer,json=body).status_code==409


def test_paypal_coupon_charges_net_and_accrues_once(client,db_session,shop,monkeypatch):
    from app.servicios.paypal_service import PayPalService
    paid(db_session,shop,100,currency='USD')
    reward=redeem(client,shop,'COUPON_15');auth=headers(shop['customer'])
    amounts=[]
    def order(**kwargs):
        amounts.append(kwargs['amount'])
        return {'order_id':'POINTS-ORDER','approval_url':'https://example.com/approve'}
    monkeypatch.setattr(PayPalService,'create_order',order)
    monkeypatch.setattr(PayPalService,'capture_order',lambda order_id:{'status':'COMPLETED','capture_id':'POINTS-CAPTURE'})
    response=client.post('/api/v1/reservations/paypal-order',headers=auth,json={
        'branch_id':shop['origin'],'coupon_code':reward['code'],
        'items':[{'variant_id':shop['variant'].id,'quantity':2}]})
    assert response.status_code==201,response.text
    assert amounts==[85]
    assert response.json()['reservation']['coupon_discount_amount']==15
    for _ in range(2):
        capture=client.post('/api/v1/reservations/paypal-capture',headers=auth,json={'order_id':'POINTS-ORDER'})
        assert capture.status_code==200,capture.text
    account=client.get('/api/v1/own/loyalty',headers=auth).json()
    assert account['balance']==8 and account['rewards'][0]['status']=='USED'


def test_coupon_allocates_cents_exactly_and_keeps_legacy_cap():
    from types import SimpleNamespace
    from app.servicios.puntos_service import discount
    lines=[dict(unit_price=19.99,subtotal=59.97,quantity=3),dict(unit_price=1.01,subtotal=2.02,quantity=2)]
    result,total,savings=discount(lines,SimpleNamespace(discount_percent=7,max_discount=None))
    assert total==Decimal('57.65') and savings==Decimal('4.34')
    assert sum(Decimal(str(i['subtotal'])) for i in result)==total
    _,total,savings=discount([dict(unit_price=1000,subtotal=1000,quantity=1)],
        SimpleNamespace(discount_percent=10,max_discount=20),'BOB')
    assert total==980 and savings==20


def test_loyalty_upgrade_is_additive_and_idempotent():
    from sqlalchemy import create_engine,text,inspect
    from app.base_datos import Base
    from app.nucleo.esquema_puntos import ensure_loyalty_schema
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.exec_driver_sql('DROP TABLE loyalty_rewards')
        conn.exec_driver_sql('CREATE TABLE loyalty_rewards (id varchar(36) PRIMARY KEY, code varchar(30), discount_amount numeric(10,2))')
        conn.exec_driver_sql("INSERT INTO loyalty_rewards(id,code,discount_amount) VALUES ('legacy','PRIVATE-OLD',0)")
        ensure_loyalty_schema(conn)
        ensure_loyalty_schema(conn)
        legacy=conn.execute(text('SELECT reward_type,points_cost,discount_percent,max_discount FROM loyalty_rewards')).one()
        assert tuple(legacy)==('COUPON',100,10,20)
        assert 'fulfilled_at' in {c['name'] for c in inspect(conn).get_columns('loyalty_rewards')}
    engine.dispose()
