"""Exercise tenancy through the real API, including forbidden cross-company IDs."""
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select
from app.nucleo.seguridad import create_access_token, get_password_hash
from app.nucleo.esquema_saas import ensure_saas_schema
from app.modelos import Usuario, Sucursal, Categoria, Producto, VarianteProducto, Talla, Color, Stock, Pago, Reserva
from app.modelos.saas import ROOT_TENANT_ID, Empresa, Suscripcion, Plan, PagoSuscripcion, PRO_PRICE_USD, PRO_DURATION_DAYS, PRO_ANNUAL_PRICE_USD, PRO_ANNUAL_DURATION_DAYS
from app.servicios.saas_service import utcnow
from app.servicios.paypal_service import PayPalService


def headers(user):
    return {'Authorization':'Bearer '+create_access_token(subject=user.id, claims={'role':user.role})}


@pytest.fixture
def companies(client, db_session):
    db = db_session
    ensure_saas_schema(db.get_bind())
    root = Usuario(email='platform@example.com', full_name='Platform Owner', role='ADMIN',
                is_saas_admin=True, tenant_id=ROOT_TENANT_ID, hashed_password=get_password_hash('Platform123!'))
    db.add(root); db.commit()
    result=[]
    for slug in ('moda-a','moda-b'):
        response=client.post('/api/v1/saas/companies',headers=headers(root),json={
            'name':slug,'slug':slug,'department':'La Paz','admin_name':'Administrador '+slug,
            'admin_email':slug+'@example.com','admin_password':'Company123!'})
        assert response.status_code==201,response.text
        tenant_id=response.json()['id']
        admin=db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.tenant_id==tenant_id).first()
        result.append((tenant_id,admin))
    return root,result


def create_branch(client,admin,name='Centro'):
    return client.post('/api/v1/branches',headers=headers(admin),json={
        'name':name,'city':'La Paz','address':'Av. Principal'})


def paid_upgrade(client, db, admin, monkeypatch):
    from app.configuracion import settings
    monkeypatch.setattr(settings, 'PAYPAL_CLIENT_ID', 'test-client')
    monkeypatch.setattr(settings, 'PAYPAL_CLIENT_SECRET', 'test-secret')
    order_id='ORDER-'+str(uuid.uuid4())
    received={}
    def create_order(**kwargs):
        received.update(kwargs)
        return {'order_id':order_id,'approval_url':'https://www.sandbox.paypal.com/checkoutnow?token='+order_id}
    monkeypatch.setattr(PayPalService,'create_order',staticmethod(create_order))
    response=client.post('/api/v1/saas/subscription/paypal-order',headers=headers(admin),json={})
    assert response.status_code==200,response.text
    assert received['amount']==float(PRO_PRICE_USD) and received['currency']=='USD'
    assert received['return_url'].endswith('/subscription?checkout=return&newtab=1')
    assert client.get('/api/v1/saas/subscription',headers=headers(admin)).json()['plan_code']=='BASIC'
    payment_id=response.json()['payment_id']
    def capture_order(order):
        return {'raw':{'id':order,'status':'COMPLETED','purchase_units':[{'custom_id':payment_id,
            'payments':{'captures':[{'id':'CAPTURE-'+order,'status':'COMPLETED','amount':{'currency_code':'USD','value':str(PRO_PRICE_USD)}}]}}]}}
    monkeypatch.setattr(PayPalService,'capture_order',staticmethod(capture_order))
    response=client.post('/api/v1/saas/subscription/paypal-capture',headers=headers(admin),json={'order_id':order_id})
    assert response.status_code==200,response.text
    row=response.json()
    assert datetime.fromisoformat(row['expires_at'])-datetime.fromisoformat(row['starts_at'])==timedelta(days=30)
    return response


def test_company_isolation_and_repeated_catalog_names(client,db_session,companies):
    root,((a,admin_a),(b,admin_b))=companies
    ba=create_branch(client,admin_a).json();bb=create_branch(client,admin_b).json()
    for admin in (admin_a,admin_b):
        response=client.post('/api/v1/attributes/categories',headers=headers(admin),json={'name':'Polera'})
        assert response.status_code==201,response.text
    for admin,own,other in [(admin_a,ba,bb),(admin_b,bb,ba)]:
        rows=client.get('/api/v1/branches',headers=headers(admin)).json()
        assert [row['id'] for row in rows]==[own['id']]
        assert client.get('/api/v1/branches/'+other['id'],headers=headers(admin)).status_code==404
        assert client.put('/api/v1/branches/'+other['id'],headers=headers(admin),json={'name':'Intrusión'}).status_code==404
        assert client.get('/api/v1/saas/companies',headers=headers(admin)).status_code==403
        users=client.get('/api/v1/users',headers=headers(admin)).json()
        assert all(u['tenant_id']==admin.tenant_id for u in users)
    response=client.post('/api/v1/reports/generate',headers=headers(admin_a),json={'report_type':'inventory_by_branch'})
    assert response.status_code==200,response.text
    assert [r['branch'] for r in response.json()['rows']]==['Centro']
    assert client.post('/api/v1/reports/generate',headers=headers(admin_a),json={
        'report_type':'inventory_by_branch','branch_id':bb['id']}).status_code==400


def test_plan_limits_reopening_and_backend_ai_gate(client,db_session,companies,monkeypatch):
    root,((a,admin),(b,_))=companies
    one=create_branch(client,admin,'Uno').json()
    assert create_branch(client,admin,'Dos').status_code==201
    assert create_branch(client,admin,'Tres').status_code==409
    assert client.post('/api/v1/reports/voice',headers=headers(admin),json={'transcript':'Qué sucursal vendió más'}).status_code==403
    assert client.patch('/api/v1/branches/'+one['id']+'/toggle-status',headers=headers(admin)).status_code==200
    assert create_branch(client,admin,'Tres').status_code==201
    assert client.patch('/api/v1/branches/'+one['id']+'/toggle-status',headers=headers(admin)).status_code==409
    paid_upgrade(client, db_session, admin, monkeypatch)
    assert create_branch(client,admin,'Cuatro').status_code==201
    assert client.post('/api/v1/reports/voice',headers=headers(admin),json={'transcript':'Qué sucursal vendió más'}).status_code==200
    # Platform status changes cannot grant or replace paid plans.
    assert client.put('/api/v1/saas/companies/'+a+'/subscription',headers=headers(root),json={'plan_code':'BASIC','status':'ACTIVE'}).status_code==422


def test_subscription_expiry_suspend_and_renewal_access(client,db_session,companies):
    root,((a,admin),(b,_))=companies
    db_session.info.clear()
    sub=db_session.get(Suscripcion,a);sub.plan_code='PRO';sub.expires_at=utcnow()-timedelta(days=1);db_session.commit()
    assert create_branch(client,admin).status_code==403
    assert client.get('/api/v1/saas/subscription',headers=headers(admin)).json()['status']=='EXPIRED'
    assert client.get('/api/v1/users/me',headers=headers(admin)).status_code==200
    assert client.get('/api/v1/branches',headers=headers(admin)).status_code==200
    assert client.patch('/api/v1/saas/companies/'+a+'/status',headers=headers(root),json={'is_active':False}).status_code==200
    assert client.get('/api/v1/branches',headers=headers(admin)).status_code==403
    assert client.get('/api/v1/saas/subscription',headers=headers(admin)).json()['status']=='SUSPENDED'


def seed_product(db, tenant_id, branch_id):
    db.info.clear()
    cat=Categoria(name='Prenda',tenant_id=tenant_id);size=Talla(name='Mediana',code='M',tenant_id=tenant_id)
    color=Color(name='Azul',hex_code='#0000ff',tenant_id=tenant_id)
    db.add_all([cat,size,color]);db.flush()
    product=Producto(name='Polera '+tenant_id[:5],price=50,category_id=cat.id,tenant_id=tenant_id)
    db.add(product);db.flush()
    variant=VarianteProducto(product_id=product.id,size_id=size.id,color_id=color.id,sku='SKU-1',tenant_id=tenant_id)
    db.add(variant);db.flush();db.add(Stock(variant_id=variant.id,branch_id=branch_id,quantity=5,tenant_id=tenant_id));db.commit()
    return product,variant


def test_customer_switch_keeps_history_and_separate_carts(client,db_session,companies):
    root,((a,admin_a),(b,admin_b))=companies
    ba=create_branch(client,admin_a).json()['id'];bb=create_branch(client,admin_b).json()['id']
    pa,va=seed_product(db_session,a,ba);pb,vb=seed_product(db_session,b,bb)
    response=client.post('/api/v1/auth/register',json={'email':'customer@example.com','full_name':'Cliente Global',
        'password':'Customer123!','tenant_id':a,'branch_id':ba})
    assert response.status_code==201,response.text
    user=db_session.query(Usuario).execution_options(skip_tenant=True).filter_by(email='customer@example.com').first()
    auth=headers(user)
    assert client.post('/api/v1/cart/items',headers=auth,json={'variant_id':va.id,'quantity':1}).status_code==200
    reserve=client.post('/api/v1/reservations',headers=auth,json={'branch_id':ba,'items':[{'variant_id':va.id,'quantity':1}]})
    assert reserve.status_code==201,reserve.text
    rid=reserve.json()['id']
    assert client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':b,'branch_id':ba}).status_code==422
    assert client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':b,'branch_id':bb}).status_code==200
    # Another device keeps its own valid browsing context instead of caching
    # the other device's currently selected company under the wrong local key.
    device_a={**auth,'X-Vesta-Empresa':a,'X-Vesta-Sucursal':ba}
    assert client.get('/api/v1/users/me',headers=device_a).json()['selected_tenant_id']==a
    assert client.get('/api/v1/products/'+pa.id,headers=device_a).status_code==200
    assert client.get('/api/v1/products/'+pb.id,headers=device_a).status_code==404
    spoofed_staff={**headers(admin_a),'X-Vesta-Empresa':b,'X-Vesta-Sucursal':bb}
    assert client.get('/api/v1/products',headers=spoofed_staff).status_code==403
    assert client.get('/api/v1/cart',headers=auth).json()['items']==[]
    assert client.get('/api/v1/products/'+pa.id,headers=auth).status_code==404
    assert client.get('/api/v1/reservations',headers=auth).json()[0]['id']==rid
    assert client.post('/api/v1/cart/items',headers=auth,json={'variant_id':va.id,'quantity':1}).status_code==404
    assert client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':a,'branch_id':ba}).status_code==200
    # Reserva checkout may remove the item; create and test context once again.
    client.post('/api/v1/cart/items',headers=auth,json={'variant_id':va.id,'quantity':1})
    count=client.get('/api/v1/cart',headers=auth).json()['total_items']
    client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':b,'branch_id':bb})
    assert client.get('/api/v1/cart',headers=auth).json()['total_items']==0
    # Own old reservations can still be cancelled from the global history.
    assert client.delete('/api/v1/reservations/'+rid,headers=auth).status_code==200
    client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':a,'branch_id':ba})
    assert client.get('/api/v1/cart',headers=auth).json()['total_items']==count


def test_sync_uses_original_company_after_selection_changes(client,db_session,companies):
    root,((a,admin_a),(b,admin_b))=companies
    ba=create_branch(client,admin_a).json()['id'];bb=create_branch(client,admin_b).json()['id']
    pa,va=seed_product(db_session,a,ba)
    client.post('/api/v1/auth/register',json={'email':'offline@example.com','full_name':'Cliente Offline',
        'password':'Customer123!','tenant_id':a,'branch_id':ba})
    user=db_session.query(Usuario).execution_options(skip_tenant=True).filter_by(email='offline@example.com').first()
    auth=headers(user)
    client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':b,'branch_id':bb})
    payload={'operation_id':str(uuid.uuid4()),'account_id':user.id,'tenant_id':a,'branch_id':ba,
        'method':'POST','path':'/reservations','body':{'branch_id':ba,'items':[{'variant_id':va.id,'quantity':1}]}}
    first=client.post('/api/v1/sync/operations',headers=auth,json=payload)
    assert first.status_code==200,first.text
    assert first.json()['tenant_id']==a
    retry=client.post('/api/v1/sync/operations',headers=auth,json=payload)
    assert retry.json()['id']==first.json()['id']
    assert client.get('/api/v1/users/me',headers=auth).json()['selected_tenant_id']==b


def test_paypal_subscription_verifies_amount_tenant_and_idempotency(client,db_session,companies,monkeypatch):
    root,((a,admin_a),(b,admin_b))=companies
    db_session.info.clear()
    payment=PagoSuscripcion(id=str(uuid.uuid4()),tenant_id=a,user_id=admin_a.id,paypal_order_id='ORDER-ONE',
        amount=PRO_PRICE_USD,currency='USD',duration_days=30)
    db_session.add(payment);db_session.commit()
    raw={'id':'ORDER-ONE','status':'COMPLETED','purchase_units':[{'custom_id':payment.id,
        'payments':{'captures':[{'id':'CAPTURE-ONE','status':'COMPLETED','amount':{'currency_code':'USD','value':'19.00'}}]}}]}
    monkeypatch.setattr(PayPalService,'capture_order',staticmethod(lambda order_id:{'raw':raw}))
    path='/api/v1/saas/subscription/paypal-capture'
    assert client.post(path,headers=headers(admin_b),json={'order_id':'ORDER-ONE'}).status_code==404
    assert client.post(path,headers=headers(admin_a),json={'order_id':'ORDER-ONE'}).status_code==409
    assert client.get('/api/v1/saas/subscription',headers=headers(admin_a)).json()['plan_code']=='BASIC'
    raw['purchase_units'][0]['payments']['captures'][0]['amount']['value']=str(PRO_PRICE_USD)
    response=client.post(path,headers=headers(admin_a),json={'order_id':'ORDER-ONE'})
    assert response.status_code==200,response.text
    assert response.json()['plan_code']=='PRO' and response.json()['ai_reports']
    expiration=response.json()['expires_at']
    assert client.post(path,headers=headers(admin_a),json={'order_id':'ORDER-ONE'}).json()['expires_at']==expiration


def test_public_directory_does_not_expose_billing_or_admin(client,companies):
    response=client.get('/api/v1/saas/directory')
    assert response.status_code==200
    assert all(set(t)=={'id','name','slug','department','branches'} for t in response.json())


def test_company_admin_cannot_take_over_platform_account(client,db_session,companies):
    root,_=companies
    db_session.info.clear()
    ordinary=Usuario(email='root-staff@example.com',full_name='Administrador interno',role='ADMIN',
        tenant_id=ROOT_TENANT_ID,hashed_password=get_password_hash('Internal123!'))
    db_session.add(ordinary);db_session.commit()
    assert client.put('/api/v1/users/'+root.id,headers=headers(ordinary),json={'password':'Takeover123!'}).status_code==403
    assert client.patch('/api/v1/users/'+root.id+'/toggle-status',headers=headers(ordinary)).status_code==403
    assert client.put('/api/v1/users/'+root.id,headers=headers(root),json={'role':'CUSTOMER'}).status_code==400


def test_upgrade_of_legacy_database_keeps_records_and_scopes_unique_names(tmp_path):
    from sqlalchemy import create_engine, text, inspect
    from sqlalchemy.exc import IntegrityError
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY,email VARCHAR(255),full_name VARCHAR(100),role VARCHAR(50),created_at DATETIME)'))
        conn.execute(text("INSERT INTO users VALUES ('owner','owner@example.com','Owner','ADMIN',CURRENT_TIMESTAMP)"))
        for table,column in [('categories','name'),('sizes','code'),('colors','name'),('seasons','name'),('suppliers','company_name'),('promotions','name'),('product_variants','sku')]:
            conn.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY,{column} VARCHAR(100) UNIQUE)'))
        conn.execute(text("INSERT INTO categories VALUES ('old-category','Polera')"))
        conn.execute(text('CREATE TABLE branches (id VARCHAR(36) PRIMARY KEY,name VARCHAR(100),city VARCHAR(100), UNIQUE(name,city))'))
        conn.execute(text("INSERT INTO branches VALUES ('old-branch','Centro','La Paz')"))
        conn.execute(text('CREATE TABLE cart_items (id VARCHAR(36) PRIMARY KEY,user_id VARCHAR(36),variant_id VARCHAR(36),UNIQUE(user_id,variant_id))'))
    ensure_saas_schema(engine)
    ensure_saas_schema(engine)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT name,tenant_id FROM categories')).first()==('Polera',ROOT_TENANT_ID)
        assert conn.execute(text('SELECT count(*) FROM branches')).scalar()==1
        assert conn.execute(text('SELECT is_saas_admin FROM users WHERE id=\'owner\'')).scalar()
        conn.execute(Empresa.__table__.insert().values(id='other-company',name='Other',slug='other'))
        conn.execute(text("INSERT INTO categories (id,name,tenant_id) VALUES ('new-category','Polera','other-company')"))
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(text("INSERT INTO categories (id,name,tenant_id) VALUES ('duplicate','Polera',:tenant)"),{'tenant':ROOT_TENANT_ID})
        assert not conn.execute(text('PRAGMA foreign_key_check')).fetchall()
    engine.dispose()


def test_basic_has_no_expiry_and_cannot_be_created_as_pro(client,db_session,companies):
    root,((a,admin),_)=companies
    sub=db_session.get(Suscripcion,a)
    assert sub.plan_code=='BASIC' and sub.expires_at is None
    # Old free accounts with a saved trial date must remain usable as well.
    sub.expires_at=utcnow()-timedelta(days=100)
    db_session.commit()
    assert create_branch(client,admin).status_code==201
    row=client.get('/api/v1/saas/subscription',headers=headers(admin)).json()
    assert row['status']=='ACTIVE' and row['expires_at'] is None
    payload={'name':'No free Pro','slug':'no-free-pro','admin_name':'Administrador',
        'admin_email':'no-free-pro@example.com','admin_password':'Company123!', 'plan_code':'PRO','duration_days':366}
    assert client.post('/api/v1/saas/companies',headers=headers(root),json=payload).status_code==422
    assert client.put('/api/v1/saas/companies/'+a+'/subscription',headers=headers(root),
        json={'status':'ACTIVE','plan_code':'PRO','duration_days':366}).status_code==422


def test_fixed_terms_and_migration_preserve_existing_paid_periods(client,db_session,companies):
    from app.nucleo.politica_cobro_saas import ensure_billing_policy
    root,((a,admin),(b,_))=companies
    db_session.info.clear()
    basic=db_session.get(Suscripcion,a);basic.expires_at=utcnow()+timedelta(days=30)
    pro=db_session.get(Suscripcion,b);pro.plan_code='PRO';pro.expires_at=utcnow()+timedelta(days=12)
    expires=pro.expires_at
    db_session.get(Plan,'PRO').price_usd=99
    db_session.get(Plan,'PRO').duration_days=365
    db_session.commit()
    with db_session.get_bind().begin() as conn:
        ensure_billing_policy(conn)
        ensure_billing_policy(conn)
    db_session.expire_all()
    assert db_session.get(Suscripcion,a).expires_at is None
    from app.servicios.saas_service import aware
    assert aware(db_session.get(Suscripcion,b).expires_at)==aware(expires)
    plans=client.get('/api/v1/saas/plans',headers=headers(admin)).json()
    assert next(p for p in plans if p['code']=='BASIC')['duration_days'] is None
    pro_plan=next(p for p in plans if p['code']=='PRO')
    assert Decimal(str(pro_plan['price_usd']))==PRO_PRICE_USD and pro_plan['duration_days']==30
    assert client.put('/api/v1/saas/plans/PRO',headers=headers(root),json={
        'branch_limit':10,'ai_reports':True,'price_usd':1,'duration_days':365}).status_code==422


def test_checkout_uses_fixed_terms_and_reuses_pending_order(client,db_session,companies,monkeypatch):
    from app.configuracion import settings
    root,((a,admin),_)=companies
    monkeypatch.setattr(settings,'PAYPAL_CLIENT_ID','test-client')
    monkeypatch.setattr(settings,'PAYPAL_CLIENT_SECRET','test-secret')
    calls=[]
    def create_order(**kwargs):
        calls.append(kwargs)
        return {'order_id':'FIXED-ORDER','approval_url':'https://www.sandbox.paypal.com/checkoutnow?token=FIXED-ORDER'}
    monkeypatch.setattr(PayPalService,'create_order',staticmethod(create_order))
    # Checkout uses the fixed contract even if old plan configuration lingers.
    db_session.get(Plan,'PRO').price_usd=1
    db_session.get(Plan,'PRO').duration_days=365
    db_session.commit()
    path='/api/v1/saas/subscription/paypal-order'
    first=client.post(path,headers=headers(admin),json={})
    second=client.post(path,headers=headers(admin),json={})
    assert first.status_code==200 and first.json()==second.json()
    assert len(calls)==1 and calls[0]['amount']==float(PRO_PRICE_USD)
    payment=db_session.get(PagoSuscripcion,first.json()['payment_id'])
    assert payment.duration_days==30 and payment.amount==PRO_PRICE_USD
    assert db_session.get(Suscripcion,a).plan_code=='BASIC'


def offline_sale(admin,tenant,branch,variant,quantity=2):
    return {'operation_id':str(uuid.uuid4()),'account_id':admin.id,'tenant_id':tenant,'branch_id':branch,
        'method':'POST','path':'/payments/offline-sale','body':{'branch_id':branch,
        'customer_name':'Cliente contado','concept':'Venta offline','amount':50*quantity,'payment_type':'EFECTIVO',
        'items':[{'variant_id':variant.id,'quantity':quantity,'unit_price':50,'product_name':'Polera'}]}}


def test_offline_cash_sale_is_atomic_idempotent_and_checks_stock(client,db_session,companies):
    from app.modelos.movimiento_inventario import MovimientoInventario
    from app.modelos.operacion_sincronizacion import OperacionSincronizacion
    root,((a,admin),_)=companies
    branch=create_branch(client,admin).json()['id'];product,variant=seed_product(db_session,a,branch)
    command=offline_sale(admin,a,branch,variant,4)
    first=client.post('/api/v1/sync/operations',headers=headers(admin),json=command)
    assert first.status_code==200,first.text
    assert first.json()['status']=='PAID'
    retry=client.post('/api/v1/sync/operations',headers=headers(admin),json=command)
    assert retry.json()['id']==first.json()['id']
    assert db_session.query(Pago).count()==1 and db_session.query(MovimientoInventario).count()==1
    assert db_session.query(Stock).filter_by(variant_id=variant.id).one().quantity==1
    second=client.post('/api/v1/sync/operations',headers=headers(admin),json=offline_sale(admin,a,branch,variant,2))
    assert second.status_code==409,second.text
    assert db_session.query(Pago).count()==1 and db_session.query(OperacionSincronizacion).count()==1
    assert db_session.query(Stock).filter_by(variant_id=variant.id).one().quantity==1


def test_offline_cash_stock_conflict_can_be_corrected_without_double_charge(client, db_session, companies):
    from app.modelos.operacion_sincronizacion import OperacionSincronizacion
    from app.modelos.movimiento_inventario import MovimientoInventario
    _, ((tenant, admin), _) = companies
    branch = create_branch(client, admin).json()['id']
    _, variant = seed_product(db_session, tenant, branch)
    payload = offline_sale(admin, tenant, branch, variant, 6)
    rejected = client.post('/api/v1/sync/operations', headers=headers(admin), json=payload)
    assert rejected.status_code == 409
    assert rejected.json()['detail']['code'] == 'STOCK_INSUFFICIENT'
    assert rejected.json()['detail']['available'] == 5
    assert db_session.query(Pago).count() == db_session.query(OperacionSincronizacion).count() == 0
    payload['body']['items'][0]['quantity'] = 2
    payload['body']['amount'] = 100
    accepted = client.post('/api/v1/sync/operations', headers=headers(admin), json=payload)
    assert accepted.status_code == 200, accepted.text
    replay = client.post('/api/v1/sync/operations', headers=headers(admin), json=payload)
    assert replay.json() == accepted.json()
    assert db_session.query(Pago).count() == db_session.query(OperacionSincronizacion).count() == 1
    assert db_session.query(MovimientoInventario).count() == 1
    assert db_session.query(Stock).filter_by(variant_id=variant.id).one().quantity == 3
    payload['body']['items'][0]['quantity'] = 1
    assert client.post('/api/v1/sync/operations', headers=headers(admin), json=payload).status_code == 409
    assert db_session.query(Pago).count() == 1


def test_offline_cash_sale_rolls_back_before_receipt_and_can_retry(client,db_session,companies,monkeypatch):
    from app.servicios.pago_service import PagoService
    from fastapi import HTTPException
    root,((a,admin),_)=companies
    branch=create_branch(client,admin).json()['id'];product,variant=seed_product(db_session,a,branch)
    command=offline_sale(admin,a,branch,variant)
    original=PagoService.process_cash_payment
    def interrupt(*args,**kwargs):
        original(*args,**kwargs)
        raise HTTPException(503,'Simulated interruption before durable receipt')
    monkeypatch.setattr(PagoService,'process_cash_payment',interrupt)
    first=client.post('/api/v1/sync/operations',headers=headers(admin),json=command)
    assert first.status_code==503
    assert db_session.query(Pago).count()==0
    assert db_session.query(Stock).filter_by(variant_id=variant.id).one().quantity==5
    monkeypatch.setattr(PagoService,'process_cash_payment',original)
    assert client.post('/api/v1/sync/operations',headers=headers(admin),json=command).status_code==200
    assert db_session.query(Pago).count()==1


def test_offline_sale_rejects_changed_price_wrong_tenant_and_electronic_payment(client,db_session,companies):
    root,((a,admin),(b,other))=companies
    branch=create_branch(client,admin).json()['id'];product,variant=seed_product(db_session,a,branch)
    command=offline_sale(admin,a,branch,variant)
    command['body']['items'][0]['unit_price']=1
    assert client.post('/api/v1/sync/operations',headers=headers(admin),json=command).status_code==409
    command['body']['items'][0]['unit_price']=50
    command['body']['payment_type']='PAYPAL'
    assert client.post('/api/v1/sync/operations',headers=headers(admin),json=command).status_code==422
    assert client.post('/api/v1/sync/operations',headers=headers(other),json=command).status_code==403
    assert db_session.query(Pago).count()==0


def test_subscription_checkout_returns_to_allowed_pwa_origin_only(client,companies,monkeypatch):
    from app.configuracion import settings
    root,((_,admin),_)=companies
    monkeypatch.setattr(settings,'PAYPAL_CLIENT_ID','client')
    monkeypatch.setattr(settings,'PAYPAL_CLIENT_SECRET','secret')
    monkeypatch.setattr(settings,'CORS_ORIGINS','http://localhost:8080,http://localhost:4200')
    orders=[]
    def create_order(**kwargs):
        orders.append(kwargs)
        return {'order_id':'PWA-'+str(len(orders)),'approval_url':'https://www.sandbox.paypal.com/checkoutnow?token=PWA'}
    monkeypatch.setattr(PayPalService,'create_order',staticmethod(create_order))
    path='/api/v1/saas/subscription/paypal-order'
    response=client.post(path,headers={**headers(admin),'Origin':'http://localhost:8080'},json={})
    assert response.status_code==200,response.text
    assert orders[0]['return_url']=='http://localhost:8080/subscription?checkout=return&newtab=1'
    assert client.post(path,headers={**headers(admin),'Origin':'https://attacker.example'},json={}).status_code==400
    assert len(orders)==1


def test_company_backups_are_isolated_daily_and_never_export_credentials(client,db_session,companies,monkeypatch,tmp_path):
    import gzip,json
    from app.configuracion import settings
    from app.servicios.respaldo_service import create_backup,list_backups
    root,((a,admin),(b,other))=companies
    monkeypatch.setattr(settings,'BACKUP_DIR',str(tmp_path))
    branch=create_branch(client,admin).json()['id'];product,variant=seed_product(db_session,a,branch)
    response=client.post('/api/v1/backups',headers=headers(admin))
    assert response.status_code==201,response.text
    backup=response.json()
    assert backup['tenant_id']==a and backup['kind']=='MANUAL'
    download=client.get('/api/v1/backups/'+backup['id']+'/download',headers=headers(admin))
    assert download.status_code==200
    payload=json.loads(download.content)
    assert payload['format']=='VESTA_COMPANY_BACKUP'
    assert all(row['tenant_id']==a for name,rows in payload['tables'].items() for row in rows if 'tenant_id' in row)
    assert [row['id'] for row in payload['tables']['products']]==[product.id]
    users=payload['tables']['users']
    assert {row['id'] for row in users}=={admin.id}
    assert 'hashed_password' not in str(payload) and 'token_blacklist' not in payload['tables']
    assert 'password_reset_tokens' not in payload['tables']
    assert client.get('/api/v1/backups/'+backup['id']+'/download',headers=headers(other)).status_code==404
    assert client.get('/api/v1/backups',headers=headers(other),params={'tenant_id':a}).status_code==403
    assert client.get('/api/v1/backups',headers=headers(root),params={'tenant_id':a}).status_code==200
    auto=create_backup(a,'AUTO',db_session.get_bind())
    assert create_backup(a,'AUTO',db_session.get_bind())['id']==auto['id']
    assert len(list_backups(a))==2


def test_backup_download_checks_integrity_and_denies_branch_staff(client,db_session,companies,monkeypatch,tmp_path):
    from app.configuracion import settings
    from app.servicios.respaldo_service import company_folder
    root,((a,admin),_)=companies
    monkeypatch.setattr(settings,'BACKUP_DIR',str(tmp_path))
    record=client.post('/api/v1/backups',headers=headers(admin)).json()
    file=company_folder(a)/(record['id']+'.json.gz')
    file.write_bytes(b'corrupted')
    assert client.get('/api/v1/backups/'+record['id']+'/download',headers=headers(admin)).status_code==409
    db_session.info.clear()
    staff=Usuario(email='backup-cashier@example.com',full_name='Cashier',role='CASHIER',tenant_id=a,hashed_password='unused')
    db_session.add(staff);db_session.commit()
    assert client.post('/api/v1/backups',headers=headers(staff)).status_code==403


def test_offline_manual_cash_receipt_has_one_idempotent_commit(client,db_session,companies):
    root,((a,admin),_)=companies
    branch=create_branch(client,admin).json()['id']
    command={'operation_id':str(uuid.uuid4()),'account_id':admin.id,'tenant_id':a,'branch_id':branch,
        'method':'POST','path':'/payments/offline-sale','body':{'branch_id':branch,'customer_name':'Cliente contado',
        'concept':'Cobro manual','amount':25,'payment_type':'EFECTIVO'}}
    result=client.post('/api/v1/sync/operations',headers=headers(admin),json=command)
    assert result.status_code==200,result.text
    assert result.json()['status']=='PAID'
    assert client.post('/api/v1/sync/operations',headers=headers(admin),json=command).json()['id']==result.json()['id']
    assert db_session.query(Pago).count()==1


def test_cash_reservation_from_payments_syncs_once_without_deducting_stock_twice(client,db_session,companies):
    root,((a,admin),_)=companies
    branch=create_branch(client,admin).json()['id'];product,variant=seed_product(db_session,a,branch)
    register=client.post('/api/v1/auth/register',json={'email':'cash-reservation@example.com','full_name':'Cliente Reserva',
        'password':'Customer123!','tenant_id':a,'branch_id':branch})
    assert register.status_code==201
    customer=db_session.query(Usuario).execution_options(skip_tenant=True).filter_by(email='cash-reservation@example.com').one()
    reservation=client.post('/api/v1/reservations',headers=headers(customer),json={'branch_id':branch,'items':[{'variant_id':variant.id,'quantity':1}]}).json()
    command={'operation_id':str(uuid.uuid4()),'account_id':admin.id,'tenant_id':a,'branch_id':branch,'method':'POST','path':'/payments/offline-sale',
        'body':{'branch_id':branch,'reservation_id':reservation['id'],'customer_name':'Cliente Reserva','concept':'Cobro de reserva',
        'amount':reservation['total_amount'],'payment_type':'EFECTIVO'}}
    first=client.post('/api/v1/sync/operations',headers=headers(admin),json=command)
    assert first.status_code==200,first.text
    assert first.json()['status']=='PAID'
    assert client.post('/api/v1/sync/operations',headers=headers(admin),json=command).json()['id']==first.json()['id']
    assert db_session.query(Stock).filter_by(variant_id=variant.id).one().quantity==4
    assert db_session.query(Pago).count()==1


def test_backup_includes_only_own_customer_membership_without_other_store_selection(client,db_session,companies,monkeypatch,tmp_path):
    import gzip,json
    from app.configuracion import settings
    from app.modelos.saas import ClienteEmpresa
    root,((a,admin),(b,other))=companies
    branch=create_branch(client,other).json()['id']
    db_session.info.clear()
    customer=Usuario(email='shared-backup@example.com',full_name='Cliente Global',role='CUSTOMER',selected_tenant_id=b,
        branch_id=branch,hashed_password='do-not-export')
    db_session.add(customer);db_session.flush();db_session.add(ClienteEmpresa(user_id=customer.id,tenant_id=a));db_session.commit()
    monkeypatch.setattr(settings,'BACKUP_DIR',str(tmp_path))
    backup=client.post('/api/v1/backups',headers=headers(admin)).json()
    result=client.get('/api/v1/backups/'+backup['id']+'/download',headers=headers(admin))
    payload=json.loads(result.content)
    users={row['id']:row for row in payload['tables']['users']}
    assert customer.id in users and other.id not in users
    assert users[customer.id]['branch_id'] is None
    assert 'selected_tenant_id' not in users[customer.id] and 'hashed_password' not in users[customer.id]


def test_subscription_invoice_pdf_download(client, db_session, companies):
    root, ((a, admin), (b, other)) = companies
    payment = PagoSuscripcion(
        id=str(uuid.uuid4()),
        tenant_id=a,
        user_id=admin.id,
        paypal_order_id='ORD-INVOICE-1',
        capture_id='CAP-INVOICE-1',
        amount=PRO_PRICE_USD,
        currency='USD',
        duration_days=PRO_DURATION_DAYS,
        status='PAID',
    )
    db_session.add(payment)
    db_session.commit()

    resp = client.get(f'/api/v1/saas/subscription/payments/{payment.id}/invoice', headers=headers(admin))
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'application/pdf'
    assert b'%PDF' in resp.content[:10]

    assert client.get(f'/api/v1/saas/subscription/payments/{payment.id}/invoice', headers=headers(other)).status_code == 404

    payment_pending = PagoSuscripcion(
        id=str(uuid.uuid4()),
        tenant_id=a,
        user_id=admin.id,
        paypal_order_id='ORD-PENDING-1',
        amount=PRO_PRICE_USD,
        currency='USD',
        duration_days=PRO_DURATION_DAYS,
        status='PENDING',
    )
    db_session.add(payment_pending)
    db_session.commit()
    assert client.get(f'/api/v1/saas/subscription/payments/{payment_pending.id}/invoice', headers=headers(admin)).status_code == 409


def test_annual_and_monthly_subscription_billing(client, db_session, monkeypatch, companies):
    root, ((a, admin), (b, other)) = companies
    monkeypatch.setattr('app.configuracion.settings.PAYPAL_CLIENT_ID', 'test-client')
    monkeypatch.setattr('app.configuracion.settings.PAYPAL_CLIENT_SECRET', 'test-secret')
    created_orders = []

    def mock_create_order(amount, currency, description, custom_id, request_id, return_url, cancel_url):
        order_id = f'ORD-MOCK-{len(created_orders)+1}'
        created_orders.append({'order_id': order_id, 'amount': amount, 'description': description})
        return {'order_id': order_id, 'approval_url': f'https://www.sandbox.paypal.com/checkoutnow?token={order_id}'}

    monkeypatch.setattr(PayPalService, 'create_order', mock_create_order)

    # 1. Checkout monthly
    resp_m = client.post('/api/v1/saas/subscription/paypal-order', json={'billing_cycle': 'monthly'}, headers=headers(admin))
    assert resp_m.status_code == 200
    assert resp_m.json()['amount'] == float(PRO_PRICE_USD)
    assert resp_m.json()['duration_days'] == PRO_DURATION_DAYS

    # 2. Checkout annual
    resp_y = client.post('/api/v1/saas/subscription/paypal-order', json={'billing_cycle': 'annual'}, headers=headers(admin))
    assert resp_y.status_code == 200
    assert resp_y.json()['amount'] == float(PRO_ANNUAL_PRICE_USD)
    assert resp_y.json()['duration_days'] == PRO_ANNUAL_DURATION_DAYS

    # 3. Capture annual order
    def mock_capture_order(order_id):
        return {
            'status': 'COMPLETED',
            'raw': {
                'id': order_id,
                'status': 'COMPLETED',
                'purchase_units': [{
                    'payments': {
                        'captures': [{
                            'id': f'CAP-{order_id}',
                            'status': 'COMPLETED',
                            'amount': {'currency_code': 'USD', 'value': str(PRO_ANNUAL_PRICE_USD)},
                        }]
                    }
                }]
            }
        }

    monkeypatch.setattr(PayPalService, 'capture_order', mock_capture_order)
    order_id_y = resp_y.json()['order_id']
    resp_cap = client.post('/api/v1/saas/subscription/paypal-capture', json={'order_id': order_id_y}, headers=headers(admin))
    assert resp_cap.status_code == 200
    assert resp_cap.json()['plan_code'] == 'PRO'

    # Verify payments listing returns duration_days
    payments_resp = client.get('/api/v1/saas/subscription/payments', headers=headers(admin))
    assert payments_resp.status_code == 200
    p_data = [p for p in payments_resp.json() if p['order_id'] == order_id_y][0]
    assert p_data['status'] == 'PAID'
    assert p_data['duration_days'] == PRO_ANNUAL_DURATION_DAYS


def test_cumulative_subscription_extension(client, db_session, monkeypatch, companies):
    from datetime import datetime, timezone, timedelta
    root, ((a, admin), (b, other)) = companies
    now = datetime.now(timezone.utc)
    initial_exp = now + timedelta(days=31)  # expires ~Nov 23

    sub = db_session.get(Suscripcion, a)
    sub.plan_code = 'PRO'
    sub.status = 'ACTIVE'
    sub.starts_at = now
    sub.expires_at = initial_exp
    db_session.commit()

    # Admin purchases another month
    order_id = 'ORD-CUMULATIVE-1'
    payment = PagoSuscripcion(
        id=str(uuid.uuid4()),
        tenant_id=a,
        user_id=admin.id,
        paypal_order_id=order_id,
        amount=PRO_PRICE_USD,
        currency='USD',
        duration_days=PRO_DURATION_DAYS,
        status='PENDING',
    )
    db_session.add(payment)
    db_session.commit()

    def mock_capture(ord_id):
        return {
            'status': 'COMPLETED',
            'raw': {
                'id': ord_id,
                'status': 'COMPLETED',
                'purchase_units': [{
                    'payments': {
                        'captures': [{
                            'id': f'CAP-{ord_id}',
                            'status': 'COMPLETED',
                            'amount': {'currency_code': 'USD', 'value': str(PRO_PRICE_USD)},
                        }]
                    }
                }]
            }
        }

    monkeypatch.setattr(PayPalService, 'capture_order', mock_capture)
    resp = client.post('/api/v1/saas/subscription/paypal-capture', json={'order_id': order_id}, headers=headers(admin))
    assert resp.status_code == 200

    db_session.refresh(sub)
    expected_exp = initial_exp + timedelta(days=PRO_DURATION_DAYS)
    # The subscription expiration must accumulate onto the existing future expiration date
    assert abs((sub.expires_at.replace(tzinfo=timezone.utc) - expected_exp).total_seconds()) < 2

