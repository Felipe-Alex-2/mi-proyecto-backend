"""Plan creation permissions and real fixed-term Max checkout (mocked PayPal)."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock
from sqlalchemy import create_engine, text, inspect
from app.modelos.saas import Plan, Suscripcion, PagoSuscripcion
from app.servicios.saas_service import utcnow, aware
from app.servicios.paypal_service import PayPalService
from app.configuracion import settings
from app.nucleo.esquema_saas import ensure_plan_catalog
from tests.test_saas import companies, headers


def test_max_catalog_and_platform_only_creation(client, db_session, companies):
    root, ((_, admin), _) = companies
    plans = client.get('/api/v1/saas/plans', headers=headers(admin)).json()
    maximum = next(p for p in plans if p['code'] == 'MAX')
    assert Decimal(str(maximum['price_usd'])) == 50
    assert maximum['duration_days'] == 30 and maximum['branch_limit'] == 25 and maximum['ai_reports']
    data = dict(name='Empresarial', price_usd=75, duration_days=60, branch_limit=40, ai_reports=True)
    assert client.post('/api/v1/saas/plans', headers=headers(admin), json=data).status_code == 403
    created = client.post('/api/v1/saas/plans', headers=headers(root), json=data)
    assert created.status_code == 201, created.text
    assert created.json()['code'] not in ('BASIC', 'PRO', 'MAX')
    assert client.post('/api/v1/saas/plans', headers=headers(root), json={**data, 'name':'empresarial'}).status_code == 409
    for changes in ({'price_usd': 0}, {'price_usd': 50.123}, {'duration_days': 0}, {'branch_limit': 0}, {'name': '  '}):
        assert client.post('/api/v1/saas/plans', headers=headers(root), json={**data, **changes}).status_code == 422


def test_max_checkout_amount_capture_and_retry(client, db_session, companies, monkeypatch):
    _, ((tenant, admin), (_, other)) = companies
    monkeypatch.setattr(settings, 'PAYPAL_CLIENT_ID', 'test')
    monkeypatch.setattr(settings, 'PAYPAL_CLIENT_SECRET', 'test')
    create = Mock(return_value={'order_id':'MAX-ORDER', 'approval_url':'https://sandbox.paypal.com/approve'})
    monkeypatch.setattr(PayPalService, 'create_order', create)
    request = {'plan_code':'MAX', 'billing_cycle':'monthly', 'amount':1}
    response = client.post('/api/v1/saas/subscription/paypal-order', headers=headers(admin), json=request)
    assert response.status_code == 200, response.text
    assert create.call_args.kwargs['amount'] == 50
    assert 'Max' in create.call_args.kwargs['description']
    payment = db_session.get(PagoSuscripcion, response.json()['payment_id'])
    assert payment.plan_code == 'MAX' and payment.plan_name == 'Max'
    capture = Mock(return_value={'raw':{'id':'MAX-ORDER','status':'COMPLETED','purchase_units':[{
        'custom_id':payment.id, 'payments':{'captures':[{'id':'MAX-CAPTURE', 'status':'COMPLETED',
        'amount':{'currency_code':'USD','value':'50.00'}}]}}]}})
    monkeypatch.setattr(PayPalService, 'capture_order', capture)
    assert client.post('/api/v1/saas/subscription/paypal-capture', headers=headers(other), json={'order_id':'MAX-ORDER'}).status_code == 404
    confirmed = client.post('/api/v1/saas/subscription/paypal-capture', headers=headers(admin), json={'order_id':'MAX-ORDER'})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['plan_code'] == 'MAX' and confirmed.json()['branch_limit'] == 25
    expiry = db_session.get(Suscripcion, tenant).expires_at
    repeated = client.post('/api/v1/saas/subscription/paypal-capture', headers=headers(admin), json={'order_id':'MAX-ORDER'})
    assert repeated.status_code == 200
    assert db_session.get(Suscripcion, tenant).expires_at == expiry
    capture.assert_called_once()
    history = client.get('/api/v1/saas/subscription/payments', headers=headers(admin)).json()
    assert history[0]['plan_name'] == 'Max'
    invoice = client.get(f'/api/v1/saas/subscription/payments/{payment.id}/invoice', headers=headers(admin))
    assert invoice.status_code == 200 and invoice.content.startswith(b'%PDF')


def test_custom_plan_checkout_and_preserved_remaining_days(client, db_session, companies, monkeypatch):
    root, ((tenant, admin), _) = companies
    created = client.post('/api/v1/saas/plans', headers=headers(root), json=dict(
        name='Equipo', price_usd=65, duration_days=45, branch_limit=30, ai_reports=False)).json()
    sub = db_session.get(Suscripcion, tenant)
    sub.plan_code = 'PRO'; sub.expires_at = utcnow() + timedelta(days=10)
    previous = aware(sub.expires_at); db_session.commit()
    monkeypatch.setattr(settings, 'PAYPAL_CLIENT_ID', 'test')
    monkeypatch.setattr(settings, 'PAYPAL_CLIENT_SECRET', 'test')
    monkeypatch.setattr(PayPalService, 'create_order', Mock(return_value={'order_id':'CUSTOM-ORDER','approval_url':'https://sandbox.paypal.com/approve'}))
    for invalid in ({'plan_code':'BASIC'}, {'plan_code':'UNKNOWN'}, {'plan_code':'MAX','billing_cycle':'annual'}):
        assert client.post('/api/v1/saas/subscription/paypal-order', headers=headers(admin), json=invalid).status_code == 422
    response = client.post('/api/v1/saas/subscription/paypal-order', headers=headers(admin), json={'plan_code':created['code']})
    assert response.status_code == 200, response.text
    assert response.json()['amount'] == 65 and response.json()['duration_days'] == 45
    capture = Mock(return_value={'raw':{'id':'CUSTOM-ORDER','status':'COMPLETED','purchase_units':[{
        'payments':{'captures':[{'id':'CUSTOM-CAPTURE','status':'COMPLETED','amount':{'currency_code':'USD','value':'65.00'}}]}}]}})
    monkeypatch.setattr(PayPalService, 'capture_order', capture)
    result = client.post('/api/v1/saas/subscription/paypal-capture', headers=headers(admin), json={'order_id':'CUSTOM-ORDER'})
    assert result.status_code == 200, result.text
    assert result.json()['plan_code'] == created['code'] and not result.json()['ai_reports']
    assert aware(db_session.get(Suscripcion, tenant).expires_at) == previous + timedelta(days=45)


def test_catalog_upgrade_preserves_legacy_receipts_and_is_repeatable():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        Plan.__table__.create(conn)
        conn.execute(text('CREATE TABLE saas_subscription_payments (id VARCHAR(36) PRIMARY KEY, amount NUMERIC)'))
        conn.execute(text("INSERT INTO saas_subscription_payments VALUES ('legacy',20)"))
        ensure_plan_catalog(conn); ensure_plan_catalog(conn)
        assert conn.execute(text('SELECT plan_code,amount FROM saas_subscription_payments')).one() == ('PRO',20)
        assert conn.execute(text("SELECT count(*) FROM saas_plans WHERE code='MAX'")).scalar() == 1
        assert 'plan_name' in {c['name'] for c in inspect(conn).get_columns('saas_subscription_payments')}
    engine.dispose()
