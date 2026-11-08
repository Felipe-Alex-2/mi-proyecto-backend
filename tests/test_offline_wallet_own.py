import uuid
import pytest
from sqlalchemy import event
from tests.test_saas import companies,headers
from tests.test_aporte_propio import shop,paid,stock_qty
from tests.test_wallet import mock_paypal,fund
from app.modelos.wallet import CuentaWallet,MovimientoWallet
from app.modelos.reserva import Reserva
from app.modelos.aporte_propio import BeneficioPuntos,CambioPrenda
from app.modelos.operacion_sincronizacion import OperacionSincronizacion


def command(shop,path,body):
    return dict(operation_id=str(uuid.uuid4()),tenant_id=shop['tenant'],branch_id=shop['origin'],path=path,method='POST',body=body)


def wallet_command(shop,expected=50):
    return command(shop,'/reservations',dict(branch_id=shop['origin'],payment_method='WALLET',
        request_id=str(uuid.uuid4()),_wallet_expected_total=expected,items=[dict(variant_id=shop['variant'].id,quantity=1)]))


def test_wallet_sync_debits_once_and_returns_confirmed_balance(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);fund(client,shop);auth=headers(shop['customer'])
    payload=wallet_command(shop)
    response=client.post('/api/v1/sync/operations',headers=auth,json=payload)
    assert response.status_code==200,response.text
    assert response.json()['payment_status']=='PAID' and response.json()['wallet_balance']==50
    retry=client.post('/api/v1/sync/operations',headers=auth,json=payload)
    assert retry.json()==response.json()
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    assert db_session.query(MovimientoWallet).filter(MovimientoWallet.reservation_id.isnot(None)).count()==1


@pytest.mark.parametrize('conflict',['price','balance','stock'])
def test_wallet_conflicts_do_not_partially_spend_or_reserve(client,db_session,shop,monkeypatch,conflict):
    mock_paypal(monkeypatch);fund(client,shop,10 if conflict=='balance' else 100)
    if conflict=='stock':
        from app.modelos.stock import Stock
        db_session.query(Stock).filter(Stock.variant_id==shop['variant'].id).update({'quantity':0});db_session.commit()
    result=client.post('/api/v1/sync/operations',headers=headers(shop['customer']),json=wallet_command(shop,49 if conflict=='price' else 50))
    assert result.status_code==409,result.text
    assert db_session.query(Reserva).count()==0 and db_session.query(OperacionSincronizacion).count()==0
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==(10 if conflict=='balance' else 100)


@pytest.mark.parametrize('kind',['wallet','exchange','redeem'])
def test_operation_and_receipt_commit_together_or_rollback(client,db_session,shop,monkeypatch,kind):
    if kind=='wallet':
        mock_paypal(monkeypatch);fund(client,shop);payload=wallet_command(shop);user=shop['customer']
    else:
        sale=paid(db_session,shop,100,currency='USD')
        if kind=='exchange':
            user=shop['admin'];payload=command(shop,'/own/exchanges',dict(request_id=str(uuid.uuid4()),payment_id=sale.id,
                original_line=0,new_variant_id=shop['replacement'].id,quantity=1,resellable=True,confirm_cash=True,expected_difference=20))
        else:
            user=shop['customer'];payload=command(shop,'/own/loyalty/redeem',dict(request_id=str(uuid.uuid4()),reward='COUPON_7'))
    def fail_receipt(session,*args):
        if any(isinstance(r,OperacionSincronizacion) for r in session.new):raise RuntimeError('simulated receipt failure')
    event.listen(db_session,'before_flush',fail_receipt)
    try:
        with pytest.raises(RuntimeError,match='simulated receipt failure'):
            client.post('/api/v1/sync/operations',headers=headers(user),json=payload)
    finally:event.remove(db_session,'before_flush',fail_receipt)
    assert db_session.query(OperacionSincronizacion).count()==0
    assert db_session.query(BeneficioPuntos).count()==0 and db_session.query(CambioPrenda).count()==0
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    if kind=='wallet':assert client.get('/api/v1/wallet',headers=headers(user)).json()['balance']==100


def test_exchange_and_redeem_sync_are_idempotent_and_role_scoped(client,db_session,shop):
    sale=paid(db_session,shop,100,currency='USD')
    redeem=command(shop,'/own/loyalty/redeem',dict(request_id=str(uuid.uuid4()),reward='COUPON_7'))
    auth=headers(shop['customer'])
    first=client.post('/api/v1/sync/operations',headers=auth,json=redeem)
    assert first.status_code==200,first.text
    assert first.json()['code'].startswith('VESTA-')
    assert client.post('/api/v1/sync/operations',headers=auth,json=redeem).json()==first.json()
    assert client.get('/api/v1/own/loyalty',headers=auth).json()['balance']==5
    change=command(shop,'/own/exchanges',dict(request_id=str(uuid.uuid4()),payment_id=sale.id,
        original_line=0,new_variant_id=shop['replacement'].id,quantity=1,resellable=True,confirm_cash=True,expected_difference=20))
    assert client.post('/api/v1/sync/operations',headers=auth,json=change).status_code==403
    staff=headers(shop['admin'])
    first=client.post('/api/v1/sync/operations',headers=staff,json=change)
    assert first.status_code==200,first.text
    assert first.json()['receipt_payment_id']
    assert client.post('/api/v1/sync/operations',headers=staff,json=change).json()==first.json()
    assert db_session.query(CambioPrenda).count()==1


def test_offline_mystery_claim_and_coupon_application_use_existing_validations(client,db_session,shop):
    import json
    from app.modelos.pago import Pago
    paid(db_session,shop,200,currency='USD')
    customer=headers(shop['customer']);staff=headers(shop['admin'])
    mystery=client.post('/api/v1/own/loyalty/redeem',headers=customer,json={'request_id':str(uuid.uuid4()),'reward':'MYSTERY'}).json()
    payload=command(shop,'/own/loyalty/claim',dict(code=mystery['code'],branch_id=shop['origin'],variant_id=shop['variant'].id))
    first=client.post('/api/v1/sync/operations',headers=staff,json=payload)
    assert first.status_code==200,first.text
    assert first.json()['status']=='CLAIMED'
    assert client.post('/api/v1/sync/operations',headers=staff,json=payload).json()==first.json()
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==4
    coupon=client.post('/api/v1/own/loyalty/redeem',headers=customer,json={'request_id':str(uuid.uuid4()),'reward':'COUPON_7'}).json()
    db_session.info.clear()
    sale=Pago(id=str(uuid.uuid4()),tenant_id=shop['tenant'],branch_id=shop['origin'],payment_code='PENDING-COUPON',
        customer_id=shop['customer'].id,customer_name='Cliente',concept='Prenda',currency='USD',amount=50,status='PENDING',
        payment_type='EFECTIVO',items_detail=json.dumps([dict(variant_id=shop['variant'].id,quantity=1,unit_price=50,subtotal=50)]))
    db_session.add(sale);db_session.commit()
    payload=command(shop,'/own/loyalty/apply',dict(code=coupon['code'],payment_id=sale.id))
    first=client.post('/api/v1/sync/operations',headers=staff,json=payload)
    assert first.status_code==200,first.text
    assert client.post('/api/v1/sync/operations',headers=staff,json=payload).json()==first.json()
    db_session.refresh(sale);assert float(sale.amount)==46.5
