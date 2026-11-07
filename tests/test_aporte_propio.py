import json
import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.modelos import Usuario, Pago, Stock, VarianteProducto, Talla
from app.modelos.saas import ClienteEmpresa
from app.modelos.aporte_propio import CambioPrenda, MovimientoPuntos, EntregaDomicilio
from app.nucleo.seguridad import get_password_hash
from app.servicios.aporte_propio_service import now
from tests.test_saas import companies, headers, create_branch, seed_product


@pytest.fixture
def shop(client, db_session, companies):
    root, ((tenant, admin), (other_tenant, other_admin)) = companies
    origin = create_branch(client, admin, 'Central').json()['id']
    destination = create_branch(client, admin, 'Norte').json()['id']
    foreign = create_branch(client, other_admin, 'Otra').json()['id']
    product, variant = seed_product(db_session, tenant, origin)
    db_session.info.clear()
    customer = Usuario(email='cliente-own@example.com', full_name='Cliente Aporte', role='CUSTOMER',
        tenant_id=None, selected_tenant_id=tenant, branch_id=origin,
        hashed_password=get_password_hash('Customer123!'))
    db_session.add(customer); db_session.flush()
    db_session.add(ClienteEmpresa(user_id=customer.id, tenant_id=tenant))
    size = Talla(name='Grande', code='L', tenant_id=tenant)
    db_session.add(size); db_session.flush()
    replacement = VarianteProducto(tenant_id=tenant, product_id=product.id, size_id=size.id,
        color_id=variant.color_id, sku='SKU-L', price_override=120)
    db_session.add(replacement); db_session.flush()
    db_session.add(Stock(tenant_id=tenant, variant_id=replacement.id, branch_id=origin, quantity=3))
    db_session.commit()
    return dict(tenant=tenant, admin=admin, customer=customer, origin=origin,
        destination=destination, foreign=foreign, variant=variant, replacement=replacement,
        other_admin=other_admin, product=product)


def paid(db, shop, amount=100, currency='BOB', quantity=1):
    db.info.clear()
    row = Pago(id=str(uuid.uuid4()), tenant_id=shop['tenant'], payment_code='TEST-'+uuid.uuid4().hex[:8],
        branch_id=shop['origin'], customer_id=shop['customer'].id, customer_name='Cliente Aporte',
        amount=amount, currency=currency, concept='Compra de prendas', status='PAID',
        payment_type='EFECTIVO', paid_at=now(), items_detail=json.dumps([
            dict(variant_id=shop['variant'].id, quantity=quantity, unit_price=amount/quantity,
                 subtotal=amount, product_name='Polera', size='M', color='Azul')]))
    db.add(row); db.commit()
    return row


def stock_qty(db, branch, variant):
    db.info.clear()
    row=db.query(Stock).filter_by(branch_id=branch, variant_id=variant).first()
    return row.quantity if row else 0


def test_exchange_stock_receipt_and_idempotency(client, db_session, shop):
    p=paid(db_session,shop)
    request=dict(request_id=str(uuid.uuid4()),payment_id=p.id,original_line=0,
        new_variant_id=shop['replacement'].id,quantity=1,resellable=True,
        confirm_cash=True,expected_difference=20)
    auth=headers(shop['admin'])
    response=client.post('/api/v1/own/exchanges',headers=auth,json=request)
    assert response.status_code==201,response.text
    receipt=response.json()['receipt_payment_id']
    again=client.post('/api/v1/own/exchanges',headers=auth,json=request)
    assert again.json()['id']==response.json()['id']
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==6
    assert stock_qty(db_session,shop['origin'],shop['replacement'].id)==2
    assert db_session.get(Pago,receipt).amount==Decimal('20')
    assert db_session.get(Pago,p.id).amount==Decimal('100')
    pdf=client.get('/api/v1/payments/'+receipt+'/invoice-pdf',headers=auth)
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    request['request_id']=str(uuid.uuid4())
    assert client.post('/api/v1/own/exchanges',headers=auth,json=request).status_code==409
    assert client.post('/api/v1/own/exchanges',headers=headers(shop['customer']),json=request).status_code==403


def test_exchange_validates_price_deadline_stock_and_rollback(client,db_session,shop):
    p=paid(db_session,shop)
    request=dict(request_id=str(uuid.uuid4()),payment_id=p.id,original_line=0,
        new_variant_id=shop['replacement'].id,quantity=1,resellable=True,confirm_cash=True,expected_difference=15)
    auth=headers(shop['admin'])
    assert client.post('/api/v1/own/exchanges',headers=auth,json=request).status_code==409
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    db_session.get(Pago,p.id).paid_at=now()-timedelta(days=31);db_session.commit()
    request['expected_difference']=20
    assert client.post('/api/v1/own/exchanges',headers=auth,json=request).status_code==422
    assert client.post('/api/v1/own/exchanges',headers=headers(shop['other_admin']),json=request).status_code==404


def test_transfer_conserves_stock_in_transit_and_receives_once(client,db_session,shop):
    request=dict(request_id=str(uuid.uuid4()),origin_id=shop['origin'],destination_id=shop['destination'],
                 items=[dict(variant_id=shop['variant'].id,quantity=3)])
    auth=headers(shop['admin'])
    sent=client.post('/api/v1/own/transfers',headers=auth,json=request)
    assert sent.status_code==201,sent.text
    assert client.post('/api/v1/own/transfers',headers=auth,json=request).json()['id']==sent.json()['id']
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==2
    assert stock_qty(db_session,shop['destination'],shop['variant'].id)==0
    for _ in range(2):
        response=client.post('/api/v1/own/transfers/'+sent.json()['id']+'/receive',headers=auth)
        assert response.status_code==200,response.text
    assert stock_qty(db_session,shop['destination'],shop['variant'].id)==3
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==2
    request.update(request_id=str(uuid.uuid4()),destination_id=shop['foreign'])
    assert client.post('/api/v1/own/transfers',headers=auth,json=request).status_code==404


def test_transfer_lot_rolls_back_and_manager_only_operates_assigned_branch(client,db_session,shop):
    request=dict(request_id=str(uuid.uuid4()),origin_id=shop['origin'],destination_id=shop['destination'],items=[
        dict(variant_id=shop['variant'].id,quantity=2),dict(variant_id=shop['replacement'].id,quantity=99)])
    assert client.post('/api/v1/own/transfers',headers=headers(shop['admin']),json=request).status_code==409
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    manager=Usuario(tenant_id=shop['tenant'],selected_tenant_id=shop['tenant'],branch_id=shop['origin'],
        email='manager-own@example.com',full_name='Encargado',role='STORE_MANAGER',hashed_password=get_password_hash('Manager123!'))
    db_session.add(manager);db_session.commit()
    request['items']=[dict(variant_id=shop['variant'].id,quantity=1)]
    sent=client.post('/api/v1/own/transfers',headers=headers(manager),json=request)
    assert sent.status_code==201,sent.text
    assert client.post('/api/v1/own/transfers/'+sent.json()['id']+'/receive',headers=headers(manager)).status_code==403


def test_loyalty_settlement_once_currency_fee_and_redeem(client,db_session,shop):
    p=paid(db_session,shop,1000)
    db_session.info.clear();p.notes='Edición posterior';db_session.commit()
    paid(db_session,shop,1000,currency='USD')
    auth=headers(shop['customer'])
    account=client.get('/api/v1/own/loyalty',headers=auth).json()
    assert account['balance']==100 and len(account['entries'])==1
    request={'request_id':str(uuid.uuid4())}
    redeemed=client.post('/api/v1/own/loyalty/redeem',headers=auth,json=request)
    assert redeemed.status_code==201,redeemed.text
    assert client.post('/api/v1/own/loyalty/redeem',headers=auth,json=request).json()['code']==redeemed.json()['code']
    assert client.get('/api/v1/own/loyalty',headers=auth).json()['balance']==0
    assert client.post('/api/v1/own/loyalty/redeem',headers=auth,json={'request_id':str(uuid.uuid4())}).status_code==409
    assert client.get('/api/v1/own/loyalty',headers=headers(shop['admin'])).status_code==403


def test_reward_applies_to_identified_sale_and_paid_purchase_earns_net_points(client,db_session,shop):
    paid(db_session,shop,1000)
    customer_auth=headers(shop['customer']);admin_auth=headers(shop['admin'])
    reward=client.post('/api/v1/own/loyalty/redeem',headers=customer_auth,json={'request_id':str(uuid.uuid4())}).json()
    request=dict(branch_id=shop['origin'],customer_name='Cliente Aporte',customer_email=shop['customer'].email,
        concept='Venta con puntos',amount=150,currency='BOB',items=[dict(variant_id=shop['variant'].id,
        quantity=1,unit_price=150,product_name='Polera')])
    sale=client.post('/api/v1/payments',headers=admin_auth,json=request)
    assert sale.status_code==201,sale.text
    pid=sale.json()['id']
    assert sale.json()['customer_id']==shop['customer'].id
    applied=client.post('/api/v1/own/loyalty/apply',headers=admin_auth,json={'code':reward['code'],'payment_id':pid})
    assert applied.status_code==200,applied.text
    assert float(applied.json()['discount_amount'])==15
    assert client.post('/api/v1/own/loyalty/apply',headers=admin_auth,json={'code':reward['code'],'payment_id':pid}).status_code==200
    result=client.post('/api/v1/payments/'+pid+'/cash',headers=admin_auth,json={})
    assert result.status_code==200,result.text
    assert float(result.json()['amount'])==135
    assert client.get('/api/v1/own/loyalty',headers=customer_auth).json()['balance']==13


def test_delivery_fee_payment_states_and_stock_not_deducted_twice(client,db_session,shop):
    p=paid(db_session,shop)
    auth=headers(shop['customer']);admin_auth=headers(shop['admin'])
    request=dict(request_id=str(uuid.uuid4()),payment_id=p.id,recipient='Cliente Aporte',phone='70012345',
                 address='Calle Principal 123, puerta verde',zone='CENTRO')
    created=client.post('/api/v1/own/deliveries',headers=auth,json=request)
    assert created.status_code==201,created.text
    row=created.json();route='/api/v1/own/deliveries/'+row['id']
    assert float(row['fee'])==15
    assert client.post('/api/v1/own/deliveries',headers=auth,json=request).json()['id']==row['id']
    assert client.patch(route,headers=admin_auth,json={'status':'PREPARING'}).status_code==409
    assert client.patch(route,headers=auth,json={'status':'PREPARING'}).status_code==403
    result=client.post('/api/v1/payments/'+row['shipping_payment_id']+'/cash',headers=admin_auth,json={})
    assert result.status_code==200,result.text
    for state in ['PREPARING','OUT_FOR_DELIVERY','DELIVERED']:
        result=client.patch(route,headers=admin_auth,json={'status':state,'courier':'Juan Repartidor'})
        assert result.status_code==200,result.text
    assert len(result.json()['history'])==4
    assert client.patch(route,headers=admin_auth,json={'status':'PREPARING'}).status_code==409
    assert stock_qty(db_session,shop['origin'],shop['variant'].id)==5
    assert client.get('/api/v1/own/loyalty',headers=auth).json()['balance']==10
    assert client.get('/api/v1/own/deliveries',headers=headers(shop['other_admin'])).json()==[]


def test_customer_cannot_request_delivery_for_another_customer_or_reuse_purchase(client,db_session,shop):
    p=paid(db_session,shop)
    db_session.info.clear()
    other=Usuario(tenant_id=None,selected_tenant_id=shop['tenant'],branch_id=shop['origin'],
        email='other-client@example.com',full_name='Otro Cliente',role='CUSTOMER',hashed_password=get_password_hash('Customer123!'))
    db_session.add(other);db_session.commit()
    request=dict(request_id=str(uuid.uuid4()),payment_id=p.id,recipient='Otro Cliente',phone='70012345',
                 address='Calle Principal 123, puerta verde',zone='CENTRO')
    assert client.post('/api/v1/own/deliveries',headers=headers(other),json=request).status_code==404
    assert client.get('/api/v1/own/purchases',headers=headers(other)).json()==[]
    assert client.post('/api/v1/own/deliveries',headers=headers(shop['customer']),json=request).status_code==201
    request['request_id']=str(uuid.uuid4())
    assert client.post('/api/v1/own/deliveries',headers=headers(shop['customer']),json=request).status_code==409
