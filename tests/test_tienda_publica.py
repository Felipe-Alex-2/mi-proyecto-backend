"""Storefront access, personal ownership, and cross-company isolation through HTTP."""
import pytest
from tests.test_saas import companies, headers, create_branch, seed_product
from app.modelos import Usuario
from app.modelos.saas import Empresa
from app.servicios.paypal_service import PayPalService


@pytest.fixture
def stores(client, db_session, companies):
    _, ((a, admin_a), (b, admin_b)) = companies
    branch_a = create_branch(client, admin_a).json()['id']
    branch_b = create_branch(client, admin_b).json()['id']
    product_a, variant_a = seed_product(db_session, a, branch_a)
    product_b, variant_b = seed_product(db_session, b, branch_b)
    return (a, branch_a, product_a.id, variant_a.id), (b, branch_b, product_b.id, variant_b.id)


def register(client, db, store, email='shop@example.com'):
    response = client.post('/api/v1/auth/register', json={'email': email, 'password':'Customer123!',
        'full_name':'Cliente de prueba', 'tenant_id':store[0], 'branch_id':store[1]})
    assert response.status_code == 201, response.text
    return db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.email == email).one()


def test_guest_catalog_is_scoped_and_personal_actions_require_login(client, db_session, stores):
    a, b = stores
    params = {'tenant_id': a[0], 'store_branch': a[1]}
    response = client.get('/api/v1/shop/catalog/products', params=params)
    assert response.status_code == 200, response.text
    assert [p['id'] for p in response.json()['items']] == [a[2]]
    detail = client.get('/api/v1/shop/catalog/products/'+a[2], params=params)
    assert detail.status_code == 200
    assert detail.json()['variants'][0]['branch_availability'][0]['branch_id'] == a[1]
    assert client.get('/api/v1/shop/catalog/products/'+b[2], params=params).status_code == 404
    filters = client.get('/api/v1/shop/catalog/filters', params=params).json()
    assert [row['id'] for row in filters['branches']] == [a[1]]
    assert client.get('/api/v1/shop/catalog/products', params={'tenant_id':a[0], 'store_branch':b[1]}).status_code == 404
    assert client.get('/api/v1/shop/catalog/products').status_code == 422
    for path in ('/cart','/favorites','/reservations','/notifications','/virtual-fitting/profile'):
        assert client.get('/api/v1'+path).status_code == 401
    assert client.post('/api/v1/cart/items',json={'variant_id':a[3],'quantity':1}).status_code == 401
    assert client.put('/api/v1/favorites/'+a[2],json={}).status_code == 401
    assert client.post('/api/v1/reservations',json={'branch_id':a[1],'items':[{'variant_id':a[3],'quantity':1}]}).status_code == 401


def test_suspended_store_is_not_public(client, db_session, stores):
    a, _ = stores
    db_session.get(Empresa,a[0]).is_active = False
    db_session.commit()
    assert client.get('/api/v1/shop/catalog/products',params={'tenant_id':a[0],'store_branch':a[1]}).status_code == 404


def test_favorites_are_idempotent_owned_and_company_scoped(client, db_session, stores):
    a, b = stores
    first = register(client,db_session,a)
    second = register(client,db_session,a,'second@example.com')
    auth = headers(first)
    for _ in range(2):
        assert client.put('/api/v1/favorites/'+a[2],headers=auth,json={}).status_code == 200
    assert [p['id'] for p in client.get('/api/v1/favorites',headers=auth).json()] == [a[2]]
    assert client.get('/api/v1/favorites',headers=headers(second)).json() == []
    assert client.put('/api/v1/favorites/'+b[2],headers=auth,json={}).status_code == 404
    assert client.delete('/api/v1/favorites/'+a[2],headers=headers(second)).status_code == 200
    assert len(client.get('/api/v1/favorites',headers=auth).json()) == 1
    response = client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':b[0],'branch_id':b[1]})
    assert response.status_code == 200, response.text
    assert client.get('/api/v1/favorites',headers=auth).json() == []
    client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':a[0],'branch_id':a[1]})
    assert len(client.get('/api/v1/favorites',headers=auth).json()) == 1


def test_device_context_stays_pinned_when_another_device_changes_store(client, db_session, stores):
    a,b = stores
    user = register(client,db_session,a)
    auth = headers(user)
    client.put('/api/v1/saas/selection',headers=auth,json={'tenant_id':b[0],'branch_id':b[1]})
    pinned = {**auth,'X-Vesta-Tenant':a[0],'X-Vesta-Branch':a[1]}
    response = client.get('/api/v1/catalog/products',headers=pinned)
    assert response.status_code == 200,response.text
    assert [p['id'] for p in response.json()['items']] == [a[2]]
    forged = {**auth,'X-Vesta-Tenant':a[0],'X-Vesta-Branch':b[1]}
    assert client.get('/api/v1/catalog/products',headers=forged).status_code == 403


def test_cart_reservation_and_paypal_return_without_duplicate_reservation(client, db_session, stores, monkeypatch):
    a,_ = stores
    user = register(client,db_session,a)
    auth = headers(user)
    assert client.post('/api/v1/cart/items',headers=auth,json={'variant_id':a[3],'quantity':2}).status_code == 200
    assert client.get('/api/v1/cart',headers=auth).json()['total_items'] == 2
    reservation = client.post('/api/v1/reservations',headers=auth,json={'branch_id':a[1],
        'payment_method':'PAYPAL','items':[{'variant_id':a[3],'quantity':2}]})
    assert reservation.status_code == 201,reservation.text
    assert client.get('/api/v1/cart',headers=auth).json()['total_items'] == 0
    received = {}
    def create_order(**kwargs):
        received.update(kwargs)
        return {'order_id':'ORDER-SHOP','approval_url':'https://www.sandbox.paypal.com/checkoutnow?token=ORDER-SHOP'}
    monkeypatch.setattr(PayPalService,'create_order',staticmethod(create_order))
    response = client.post('/api/v1/reservations/'+reservation.json()['id']+'/paypal-order',headers={**auth,'Origin':'http://localhost:4200'},json={})
    assert response.status_code == 200,response.text
    assert received['return_url'] == 'http://localhost:4200/paypal-return'
    assert received['cancel_url'] == 'http://localhost:4200/my-reservations?checkout=cancel'
    assert len(client.get('/api/v1/reservations',headers=auth).json()) == 1
