import json,uuid
from decimal import Decimal
import pytest
from tests.test_aporte_propio import shop,paid,stock_qty
from tests.test_saas import companies,headers
from app.modelos.wallet import CuentaWallet,RecargaWallet,MovimientoWallet
from app.servicios.paypal_service import PayPalService


def mock_paypal(monkeypatch):
    orders={}
    def create(**args):
        order='ORDER-'+str(uuid.uuid4());orders[order]=args
        return {'order_id':order,'approval_url':'https://www.sandbox.paypal.com/checkoutnow?token='+order}
    def get(order):
        a=orders[order]
        return {'id':order,'status':'APPROVED','purchase_units':[{'custom_id':a['custom_id'],'amount':{'value':str(a['amount']),'currency_code':'USD'}}]}
    def capture(order):
        raw=get(order);raw['status']='COMPLETED'
        raw['purchase_units'][0]['payments']={'captures':[{'id':'CAP-'+order,'status':'COMPLETED','amount':raw['purchase_units'][0]['amount']}]}
        return {'status':'COMPLETED','capture_id':'CAP-'+order,'raw':raw}
    monkeypatch.setattr(PayPalService,'create_order',create);monkeypatch.setattr(PayPalService,'get_order',get);monkeypatch.setattr(PayPalService,'capture_order',capture)
    return orders


def fund(client,shop,amount=100):
    auth=headers(shop['customer'])
    response=client.post('/api/v1/wallet/topups',headers=auth,json={'request_id':str(uuid.uuid4()),'amount':amount})
    assert response.status_code==201,response.text
    id=response.json()['id']
    response=client.post('/api/v1/wallet/topups/'+id+'/capture',headers=auth)
    assert response.status_code==200,response.text
    return id


def test_wallet_topup_only_confirmed_once_and_owner_scoped(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);auth=headers(shop['customer'])
    request={'request_id':str(uuid.uuid4()),'amount':50}
    a=client.post('/api/v1/wallet/topups',headers=auth,json=request)
    assert a.status_code==201,a.text
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==0
    assert client.post('/api/v1/wallet/topups',headers=auth,json=request).json()['id']==a.json()['id']
    assert client.post('/api/v1/wallet/topups',headers=auth,json=dict(request,amount=100)).status_code==409
    assert client.post('/api/v1/wallet/topups',headers=auth,json=dict(request,amount=11)).status_code==422
    route='/api/v1/wallet/topups/'+a.json()['id']+'/capture'
    assert client.post(route,headers=headers(shop['admin'])).status_code==403
    for _ in range(2):
        result=client.post(route,headers=auth)
        assert result.status_code==200,result.text
        assert result.json()['balance']==50
    assert len(result.json()['entries'])==1
    assert client.get('/api/v1/own/loyalty',headers=auth).json()['balance']==0
    db_session.info.clear()
    from app.modelos.saas import ClienteEmpresa
    shop['customer'].selected_tenant_id=shop['other_admin'].tenant_id;shop['customer'].branch_id=shop['foreign']
    db_session.add(ClienteEmpresa(user_id=shop['customer'].id,tenant_id=shop['other_admin'].tenant_id));db_session.commit()
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==0
    assert client.post(route,headers=auth).status_code==404


def test_wallet_checks_capture_amount_currency_and_binding(client,db_session,shop,monkeypatch):
    orders=mock_paypal(monkeypatch);auth=headers(shop['customer'])
    result=client.post('/api/v1/wallet/topups',headers=auth,json={'request_id':str(uuid.uuid4()),'amount':10}).json()
    order=result['order_id'];orders[order]['amount']=100
    response=client.post('/api/v1/wallet/topups/'+result['id']+'/capture',headers=auth)
    assert response.status_code==409,response.text
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==0
    orders[order]['amount']=10
    original=PayPalService.capture_order
    def bad_capture(order_id):
        response=original(order_id);response['raw']['purchase_units'][0]['payments']['captures'][0]['amount']['currency_code']='EUR';return response
    monkeypatch.setattr(PayPalService,'capture_order',bad_capture)
    assert client.post('/api/v1/wallet/topups/'+result['id']+'/capture',headers=auth).status_code==409
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==0


def test_wallet_checkout_uses_server_total_and_never_reduces_stock_twice(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop);auth=headers(shop['customer'])
    result=client.post('/api/v1/reservations',headers=auth,json={'branch_id':shop['origin'],'payment_method':'WALLET','request_id':str(uuid.uuid4()),'items':[{'variant_id':shop['variant'].id,'quantity':1}]})
    assert result.status_code==201,result.text
    row=result.json();assert row['total_amount']==50 and row['payment_status']=='PAID' and row['payment_method']=='WALLET'
    assert row['exchange_code']==row['reservation_code']
    from app.modelos.reserva import Reserva
    db_session.info.clear()
    entry=db_session.query(MovimientoWallet).filter(MovimientoWallet.reservation_id==row['id']).one()
    retry=client.post('/api/v1/reservations',headers=auth,json={'branch_id':shop['origin'],'payment_method':'WALLET','request_id':entry.source_key.removeprefix('checkout:'),'items':[{'variant_id':shop['variant'].id,'quantity':1}]})
    assert retry.status_code==201 and retry.json()['id']==row['id']
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==50
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    assert client.get('/api/v1/own/loyalty',headers=auth).json()['balance']==5
    failed=client.post('/api/v1/reservations',headers=auth,json={'branch_id':shop['origin'],'payment_method':'WALLET','request_id':str(uuid.uuid4()),'items':[{'variant_id':shop['replacement'].id,'quantity':1}]})
    assert failed.status_code==409,failed.text
    assert stock_qty(db_session,shop['origin'],shop['replacement'].id)==3
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==50
    report=client.post('/api/v1/reports/generate',headers=headers(shop['admin']),json={'report_type':'sales_by_branch'}).json()
    assert report['summary']['total_USD']==50 and report['summary']['sales']==1


def test_wallet_checkout_applies_redeemed_coupon(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop);paid(db_session,shop,50,currency='USD');auth=headers(shop['customer'])
    reward=client.post('/api/v1/own/loyalty/redeem',headers=auth,json={'request_id':str(uuid.uuid4()),'reward':'COUPON_7'}).json()
    response=client.post('/api/v1/reservations',headers=auth,json={'branch_id':shop['origin'],'payment_method':'WALLET','request_id':str(uuid.uuid4()),'coupon_code':reward['code'],'items':[{'variant_id':shop['variant'].id,'quantity':1}]})
    assert response.status_code==201,response.text
    assert response.json()['total_amount']==46.5
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==53.5
    assert client.get('/api/v1/own/loyalty',headers=auth).json()['rewards'][0]['status']=='USED'
