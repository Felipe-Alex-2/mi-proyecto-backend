from datetime import date, datetime, timedelta, timezone
import uuid

import pytest

from app.modelos import Pago, Reserva, Producto, Stock, Usuario, Categoria, VarianteProducto, Talla, Color
from app.modelos.movimiento_inventario import MovimientoInventario
from app.modelos.promocion import Promocion
from app.servicios import panel_service, descuento_sugerido_service
from tests.test_branch_reports_audit import world
from tests.test_saas import companies, create_branch, headers

NOW = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(panel_service, 'local_now', lambda: NOW.astimezone(panel_service.BOLIVIA))
    monkeypatch.setattr(descuento_sugerido_service, 'local_today', lambda: date(2026, 11, 1))


def test_dashboard_period_boundaries_dedup_currency_and_customers(client, db_session, world):
    a, b, _, _, customer, users = world
    reservation = Reserva(reservation_code='DASH-RES', customer_id=customer.id, branch_id=a.id,
                          payment_status='PAID', total_amount=20, paid_at=NOW, expires_at=NOW + timedelta(days=1))
    standalone = Reserva(reservation_code='DASH-ONLY', customer_id=customer.id, branch_id=a.id,
                         payment_status='PAID', total_amount=7, paid_at=NOW, expires_at=NOW + timedelta(days=1))
    db_session.add_all([reservation, standalone]); db_session.flush()
    for code, branch, amount, currency, status, when, rid in [
        ('CURRENT', a.id, 20, 'USD', 'PAID', NOW, reservation.id),
        ('BOB', a.id, 100, 'BOB', 'PAID', NOW, None),
        ('OTHER', b.id, 30, 'USD', 'PAID', NOW, None),
        # Nov 1 at 03:59 UTC is still October in Bolivia.
        ('OCT', a.id, 40, 'USD', 'PAID', datetime(2026, 11, 1, 3, 59), None),
        ('AUG', a.id, 50, 'USD', 'PAID', datetime(2026, 8, 15, 12), None),
        ('OLD', a.id, 999, 'USD', 'PAID', datetime(2025, 11, 30, 12), None),
        ('UNPAID', a.id, 1000, 'USD', 'PENDING', NOW, None),
    ]:
        db_session.add(Pago(payment_code=code, branch_id=branch, customer_id=customer.id,
                            customer_name='Cliente', concept='Venta', amount=amount, currency=currency,
                            status=status, paid_at=when, reservation_id=rid))
    db_session.commit()
    response = client.get('/api/v1/reports/dashboard?months=1', headers=users['ADMIN'])
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['sales'] == 4 and data['customers'] == 1
    from app.configuracion import settings
    expected = {'USD': 50, 'BOB': 100}
    expected[settings.PAYPAL_CURRENCY] = expected.get(settings.PAYPAL_CURRENCY, 0) + 7
    assert {r['currency']: r['amount'] for r in data['revenue']} == expected
    assert data['date_from'] == '2026-11-01' and len(data['series']) == 1
    three = client.get('/api/v1/reports/dashboard?months=3', headers=users['ADMIN']).json()
    assert three['sales'] == 5
    assert [r['period'] for r in three['series']] == ['2026-09', '2026-10', '2026-11']
    year = client.get('/api/v1/reports/dashboard?months=12', headers=users['ADMIN']).json()
    assert year['sales'] == 6 and year['date_from'] == '2025-12-01'
    scoped = client.get('/api/v1/reports/dashboard?months=1', headers=users['STORE_MANAGER']).json()
    assert scoped['sales'] == 3 and scoped['scope'] == a.name
    assert client.get(f'/api/v1/reports/dashboard?branch_id={b.id}', headers=users['STORE_MANAGER']).status_code == 403
    assert client.get('/api/v1/reports/dashboard', headers=users['CUSTOMER']).status_code == 403
    assert client.get('/api/v1/reports/dashboard?months=2', headers=users['ADMIN']).status_code == 422


@pytest.mark.parametrize('days,discount', [(29, 0), (30, 10), (60, 15), (90, 20), (120, 25), (180, 30)])
def test_stock_age_rules_read_only_and_initial_stock_estimate(client, db_session, world, days, discount):
    _, _, product, _, _, users = world
    product.created_at = NOW - timedelta(days=days)
    db_session.commit()
    count = db_session.query(Promocion).count()
    response = client.get('/api/v1/promotions/suggestions/stock-age', headers=users['ADMIN'])
    assert response.status_code == 200, response.text
    rows = response.json()
    assert db_session.query(Promocion).count() == count
    if discount:
        assert rows[0]['discount_percent'] == discount
        assert rows[0]['days_in_stock'] == days
        assert rows[0]['estimated'] is True and rows[0]['stock'] == 23
    else:
        assert rows == []


def test_recent_restock_excludes_old_product_and_roles(client, db_session, world):
    a, b, product, variant, _, users = world
    product.created_at = NOW - timedelta(days=200)
    db_session.add(MovimientoInventario(variant_id=variant.id, branch_id=a.id, type='ENTRY', quantity=3,
                                       reason='Reposición', previous_stock=0, new_stock=3,
                                       created_at=NOW - timedelta(days=5)))
    db_session.commit()
    assert client.get('/api/v1/promotions/suggestions/stock-age', headers=users['ADMIN']).json() == []
    assert client.get('/api/v1/promotions/suggestions/stock-age', headers=users['STORE_MANAGER']).status_code == 403
    assert client.get('/api/v1/promotions/suggestions/stock-age', headers=users['CUSTOMER']).status_code == 403


def test_confirm_draft_assigns_product_and_revalidates_campaign_stock(client, db_session, world):
    _, _, product, variant, _, users = world
    product.created_at = NOW - timedelta(days=95)
    db_session.commit()
    draft = client.get('/api/v1/promotions/suggestions/stock-age', headers=users['ADMIN']).json()[0]
    payload = {key: draft[key] for key in ('name', 'description', 'discount_percent', 'start_date', 'end_date')}
    payload['product_ids'] = [product.id]
    payload['discount_percent'] = 18  # Administrator can edit before confirming.
    operation = {'operation_id': str(uuid.uuid4()), 'method': 'POST', 'path': '/promotions', 'body': payload}
    response = client.post('/api/v1/sync/operations', headers=users['ADMIN'], json=operation)
    assert response.status_code == 200, response.text
    promo_id = response.json()['id']
    db_session.refresh(product)
    assert product.promotion_id == promo_id
    assert float(db_session.get(Promocion, promo_id).discount_percent) == 18
    again = client.post('/api/v1/sync/operations', headers=users['ADMIN'], json=operation)
    assert again.json()['id'] == promo_id
    assert client.get('/api/v1/promotions/suggestions/stock-age', headers=users['ADMIN']).json() == []
    payload['name'] = 'Otra promoción'
    assert client.post('/api/v1/promotions', headers=users['ADMIN'], json=payload).status_code == 409
    assert db_session.query(Promocion).count() == 1
    product.promotion_id = None
    for stock in db_session.query(Stock).filter(Stock.variant_id == variant.id):
        stock.quantity = 0
    db_session.commit()
    assert client.post('/api/v1/promotions', headers=users['ADMIN'], json=payload).status_code == 409
    assert db_session.query(Promocion).count() == 1


def test_tenant_isolation_for_dashboard_suggestions_and_product_assignment(client, db_session, companies):
    _, ((a, admin_a), (b, admin_b)) = companies
    ba = create_branch(client, admin_a).json()['id']
    bb = create_branch(client, admin_b).json()['id']
    db_session.info.clear()
    category = Categoria(name='Privada', tenant_id=b)
    size = Talla(name='M', code='M', tenant_id=b)
    color = Color(name='Rojo', hex_code='#ff0000', tenant_id=b)
    db_session.add_all([category, size, color]); db_session.flush()
    product = Producto(name='Prenda B', price=50, category_id=category.id, tenant_id=b, created_at=NOW - timedelta(days=100))
    db_session.add(product); db_session.flush()
    variant = VarianteProducto(product_id=product.id, size_id=size.id, color_id=color.id, sku='B', tenant_id=b)
    db_session.add(variant); db_session.flush()
    db_session.add_all([Stock(variant_id=variant.id, branch_id=bb, quantity=8, tenant_id=b),
                        Pago(payment_code='PRIVATE-B', branch_id=bb, customer_name='Privado', concept='Venta',
                             amount=999, status='PAID', paid_at=NOW, tenant_id=b)])
    db_session.commit()
    assert client.get('/api/v1/reports/dashboard', headers=headers(admin_a)).json()['sales'] == 0
    assert client.get('/api/v1/reports/dashboard', headers=headers(admin_b)).json()['sales'] == 1
    assert client.get('/api/v1/promotions/suggestions/stock-age', headers=headers(admin_a)).json() == []
    assert client.get('/api/v1/promotions/suggestions/stock-age', headers=headers(admin_b)).json()[0]['product_id'] == product.id
    payload = {'name': 'Intento cruzado', 'discount_percent': 10, 'start_date': '2026-11-01',
               'end_date': '2026-11-15', 'product_ids': [product.id]}
    assert client.post('/api/v1/promotions', headers=headers(admin_a), json=payload).status_code == 404
    assert client.get(f'/api/v1/reports/dashboard?branch_id={bb}', headers=headers(admin_a)).status_code == 404


@pytest.mark.parametrize('minutes,threshold,eligible',[(4,5,False),(5,5,True),(29,30,False),(30,30,True)])
def test_suggestions_support_minute_thresholds(client, db_session, world, monkeypatch, minutes, threshold, eligible):
    _, _, product, _, _, users = world
    monkeypatch.setattr(descuento_sugerido_service, 'utc_now', lambda: NOW)
    product.created_at = NOW - timedelta(minutes=minutes)
    db_session.commit()
    response = client.get(f'/api/v1/promotions/suggestions/stock-age?min_age_minutes={threshold}',headers=users['ADMIN'])
    assert response.status_code == 200, response.text
    rows = response.json()
    assert bool(rows) == eligible
    if eligible:
        assert rows[0]['minutes_in_stock'] == minutes
        assert rows[0]['discount_percent'] == 10
        assert 'minutos' in rows[0]['reason']
    assert client.get('/api/v1/promotions/suggestions/stock-age',headers=users['ADMIN']).json() == []
