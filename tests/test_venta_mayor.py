import json
import uuid
from decimal import Decimal
import pytest
from app.modelos import Stock, Pago, Reserva
from app.servicios.paypal_service import PayPalService
from tests.test_aporte_propio import shop, paid
from tests.test_saas import companies, headers


def prepare(db, shop):
    db.info.clear()
    shop['product'].price = 10
    stock=db.query(Stock).filter_by(branch_id=shop['origin'],variant_id=shop['variant'].id).one()
    stock.quantity=200
    db.commit()


@pytest.mark.parametrize('quantity,total', [(12,120),(13,110.50),(26,221),(52,442)])
def test_cart_and_cash_reservation_apply_one_fifteen_percent_discount(client,db_session,shop,quantity,total):
    prepare(db_session,shop)
    auth=headers(shop['customer'])
    cart=client.post('/api/v1/cart/items',headers=auth,json={'variant_id':shop['variant'].id,'quantity':quantity})
    assert cart.status_code==200,cart.text
    assert cart.json()['total_items']==quantity
    assert cart.json()['total_amount']==total
    assert cart.json()['wholesale_discount_percent']==(15 if quantity>=13 else 0)
    response=client.post('/api/v1/reservations',headers=auth,json={
        'branch_id':shop['origin'],'payment_method':'EFECTIVO',
        'items':[{'variant_id':shop['variant'].id,'quantity':quantity}]})
    assert response.status_code==201,response.text
    assert response.json()['total_amount']==total
    assert response.json()['wholesale_discount_percent']==(15 if quantity>=13 else 0)
    db_session.info.clear()
    row=db_session.get(Reserva,response.json()['id'])
    lines=json.loads(row.receipt_items_detail)
    assert sum(Decimal(str(i['subtotal'])) for i in lines)==Decimal(str(total))


def test_discount_disappears_when_cart_returns_to_twelve_and_combines_different_variants(client,db_session,shop):
    prepare(db_session,shop)
    auth=headers(shop['customer'])
    a=client.post('/api/v1/cart/items',headers=auth,json={'variant_id':shop['variant'].id,'quantity':11}).json()
    assert a['wholesale_discount_percent']==0
    b=client.post('/api/v1/cart/items',headers=auth,json={'variant_id':shop['replacement'].id,'quantity':2}).json()
    assert b['total_items']==13 and b['wholesale_discount_percent']==15
    assert b['subtotal_before_wholesale']==350 and b['total_amount']==297.5
    item=next(i for i in b['items'] if i['variant_id']==shop['variant'].id)
    result=client.put('/api/v1/cart/items/'+item['id'],headers=auth,json={'quantity':10})
    assert result.status_code==200,result.text
    assert result.json()['total_items']==12 and result.json()['wholesale_discount_percent']==0
    assert result.json()['total_amount']==340


def test_paypal_order_uses_discounted_quote_and_does_not_discount_again_on_payment(client,db_session,shop,monkeypatch):
    prepare(db_session,shop)
    received={}
    def order(**kwargs):
        received.update(kwargs)
        return {'order_id':'BULK-ORDER','approval_url':'https://www.sandbox.paypal.com/approve'}
    monkeypatch.setattr(PayPalService,'create_order',staticmethod(order))
    monkeypatch.setattr(PayPalService,'capture_order',staticmethod(lambda order:{'status':'COMPLETED','capture_id':'BULK-CAPTURE'}))
    auth=headers(shop['customer'])
    response=client.post('/api/v1/reservations/paypal-order',headers=auth,json={
        'branch_id':shop['origin'],'items':[{'variant_id':shop['variant'].id,'quantity':13}]})
    assert response.status_code==201,response.text
    assert received['amount']==110.5
    capture=client.post('/api/v1/reservations/paypal-capture',headers=auth,json={'order_id':'BULK-ORDER'})
    assert capture.status_code==200,capture.text
    assert capture.json()['reservation']['total_amount']==110.5
    assert capture.json()['reservation']['wholesale_discount_amount']==19.5
    repeated=client.post('/api/v1/reservations/paypal-capture',headers=auth,json={'order_id':'BULK-ORDER'})
    assert repeated.status_code==200 and repeated.json()['reservation']['total_amount']==110.5


def test_pos_uses_catalog_prices_for_bulk_and_records_actual_net_credit(client,db_session,shop):
    prepare(db_session,shop)
    auth=headers(shop['admin'])
    sale=client.post('/api/v1/payments',headers=auth,json={
        'branch_id':shop['origin'],'customer_name':'Cliente Aporte','customer_email':shop['customer'].email,
        'concept':'Venta por mayor','amount':1,'currency':'BOB',
        'items':[{'variant_id':shop['variant'].id,'quantity':13,'unit_price':1,'product_name':'Nombre no confiable'}]})
    assert sale.status_code==201,sale.text
    assert sale.json()['amount']==110.5 and sale.json()['wholesale_discount_percent']==15
    pid=sale.json()['id']
    result=client.post('/api/v1/payments/'+pid+'/cash',headers=auth,json={})
    assert result.status_code==200,result.text
    assert result.json()['amount']==110.5
    change=client.post('/api/v1/own/exchanges',headers=auth,json={
        'request_id':str(uuid.uuid4()),'payment_id':pid,'original_line':0,
        'new_variant_id':shop['replacement'].id,'quantity':1,'resellable':True,
        'confirm_cash':True,'expected_difference':111.5})
    assert change.status_code==201,change.text
    assert float(change.json()['original_unit_price'])==8.5


def test_partial_exchanges_never_credit_more_than_the_exact_discounted_line_total(client,db_session,shop):
    prepare(db_session,shop)
    db_session.info.clear();shop['product'].price=19.99;db_session.commit()
    auth=headers(shop['admin'])
    sale=client.post('/api/v1/payments',headers=auth,json={
        'branch_id':shop['origin'],'customer_name':'Cliente Aporte','concept':'Venta precisa','amount':259.87,'currency':'BOB',
        'items':[{'variant_id':shop['variant'].id,'quantity':13,'unit_price':19.99}]})
    assert sale.status_code==201,sale.text
    pid=sale.json()['id']
    assert client.post('/api/v1/payments/'+pid+'/cash',headers=auth,json={}).status_code==200
    db_session.info.clear()
    db_session.query(Stock).filter_by(branch_id=shop['origin'],variant_id=shop['replacement'].id).one().quantity=20
    db_session.commit()
    total=Decimal(str(sale.json()['amount']))
    credited=Decimal('0')
    for quantity in [6,7]:
        target=(total*Decimal(6 if quantity==6 else 13)/13).quantize(Decimal('.01'))
        credit=target-credited
        difference=Decimal(120*quantity)-credit
        response=client.post('/api/v1/own/exchanges',headers=auth,json={
            'request_id':str(uuid.uuid4()),'payment_id':pid,'original_line':0,
            'new_variant_id':shop['replacement'].id,'quantity':quantity,'resellable':True,
            'confirm_cash':True,'expected_difference':float(difference)})
        assert response.status_code==201,response.text
        credited+=Decimal(120*quantity)-Decimal(str(response.json()['difference']))
    assert credited==total
