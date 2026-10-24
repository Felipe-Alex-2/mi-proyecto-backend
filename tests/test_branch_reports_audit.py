from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text

from app.nucleo.seguridad import create_access_token
from app.nucleo.esquema_bitacora import ensure_activity_scope_schema
from app.modelos.bitacora import Bitacora
from app.modelos.sucursal import Sucursal
from app.modelos.categoria import Categoria
from app.modelos.color import Color
from app.modelos.pago import Pago
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.reserva import Reserva
from app.modelos.talla import Talla
from app.modelos.stock import Stock
from app.modelos.usuario import Usuario


@pytest.fixture
def world(db_session):
    a = Sucursal(name="Centro", city="La Paz", address="Centro 10")
    b = Sucursal(name="Sur", city="La Paz", address="Sur 20")
    category, size, color = Categoria(name="Poleras"), Talla(name="Mediana", code="M"), Color(name="Azul", hex_code="#123456")
    db_session.add_all([a, b, category, size, color])
    db_session.flush()
    users = {}
    for role, branch in [("ADMIN", None), ("STORE_MANAGER", a.id), ("CASHIER", a.id), ("CUSTOMER", None), ("unassigned", None)]:
        user = Usuario(email=f"{role.lower()}@scope.test", full_name=role, hashed_password="unused",
                    role="STORE_MANAGER" if role == "unassigned" else role, branch_id=branch, is_active=True)
        db_session.add(user)
        db_session.flush()
        users[role] = {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}
        if role == "CUSTOMER":
            customer = user
    product = Producto(name="Polera de prueba", price=10, category_id=category.id)
    db_session.add(product)
    db_session.flush()
    variant = VarianteProducto(product_id=product.id, sku="SCOPE-M", size_id=size.id, color_id=color.id)
    db_session.add(variant)
    db_session.flush()
    db_session.add_all([Stock(variant_id=variant.id, branch_id=a.id, quantity=3), Stock(variant_id=variant.id, branch_id=b.id, quantity=20)])
    db_session.commit()
    return a, b, product, variant, customer, users


def test_branch_reports_enforce_scope_in_every_inventory_aggregation(client, world):
    a, b, _, _, _, users = world
    def report(kind, headers, **filters):
        return client.post('/api/v1/reports/generate', headers=headers, json={"report_type": kind, **filters})
    result = report('products_by_category', users['STORE_MANAGER']).json()
    assert result['rows'][0]['units'] == 3
    assert result['summary']['scope'] == 'Centro'
    result = report('low_stock', users['ADMIN'], branch_id=b.id, low_stock_threshold=25).json()
    assert len(result['rows']) == 1
    assert result['rows'][0]['branch'] == 'Sur'
    assert report('inventory_by_branch', users['STORE_MANAGER'], branch_id=b.id).status_code == 403
    assert report('inventory_by_branch', users['unassigned']).status_code == 403
    assert report('inventory_by_branch', users['CUSTOMER']).status_code == 403
    assert report('inventory_by_branch', users['ADMIN'], branch_id='missing').status_code == 400
    assert report('inventory_by_branch', users['ADMIN']).json()['summary']['most_stock_branch'] == 'Sur'


def test_sales_rank_only_paid_and_do_not_mix_currencies_or_double_count(client, db_session, world):
    a, b, _, _, customer, users = world
    now = datetime.now(timezone.utc)
    reservation = Reserva(reservation_code='RSV-REPORT', customer_id=customer.id, branch_id=b.id,
                              status='COMPLETED', payment_status='PAID', total_amount=50,
                              expires_at=now + timedelta(days=2), paid_at=now)
    db_session.add(reservation)
    db_session.flush()
    for code, branch, amount, currency, status, reservation_id in [
        ('ONE', a.id, 20, 'USD', 'PAID', None), ('TWO', b.id, 50, 'USD', 'PAID', reservation.id),
        ('PENDING', a.id, 9999, 'USD', 'PENDING', None), ('BOB', a.id, 100, 'BOB', 'PAID', None)]:
        db_session.add(Pago(payment_code=code, branch_id=branch, customer_name='Cliente', concept='Venta',
                               amount=amount, currency=currency, status=status, reservation_id=reservation_id,
                               paid_at=now if status == 'PAID' else None))
    db_session.commit()
    response = client.post('/api/v1/reports/generate', headers=users['ADMIN'], json={'report_type': 'sales_by_branch'})
    assert response.status_code == 200
    result = response.json()
    assert result['summary']['sales'] == 3
    assert result['summary']['leader_USD'] == 'Sur'
    assert result['summary']['total_USD'] == 70
    assert result['summary']['total_BOB'] == 100
    scoped = client.post('/api/v1/reports/generate', headers=users['STORE_MANAGER'], json={'report_type': 'sales_by_branch'}).json()
    assert all(row['branch'] == 'Centro' for row in scoped['rows'])
    assert client.post('/api/v1/reports/generate', headers=users['ADMIN'], json={
        'report_type': 'sales_by_branch', 'date_from': '2026-10-21', 'date_to': '2026-10-20'}).status_code == 400


def test_comparative_questions_work_without_external_ai(client, monkeypatch, world):
    from app.servicios.gemini_client import GeminiClient
    monkeypatch.setattr(GeminiClient, 'generate_text', lambda *args: pytest.fail('A basic comparison must not require Gemini'))
    a, _, _, _, _, users = world
    for question, kind in [('Qué sucursal vendió más', 'sales_by_branch'), ('Qué sucursal tiene más ropas', 'inventory_by_branch')]:
        result = client.post('/api/v1/reports/voice', headers=users['ADMIN'], json={'transcript': question})
        assert result.status_code == 200
        assert result.json()['report']['report_type'] == kind
    scoped = client.post('/api/v1/reports/voice', headers=users['STORE_MANAGER'], json={'transcript': 'Qué sucursal tiene más prendas'})
    assert scoped.status_code == 200
    assert scoped.json()['interpretation']['branch_id'] == a.id
    denied = client.post('/api/v1/reports/voice', headers=users['STORE_MANAGER'], json={'transcript': 'Ventas de Sur'})
    assert denied.status_code == 400


def test_employee_cannot_read_or_charge_another_branch(client, db_session, world):
    a, b, _, variant, _, users = world
    payment = Pago(payment_code='PRIVATE', branch_id=b.id, customer_name='Cliente', concept='Privado', amount=10)
    db_session.add(payment)
    db_session.commit()
    headers = users['CASHIER']
    assert client.get(f'/api/v1/payments/{payment.id}', headers=headers).status_code == 403
    assert client.post(f'/api/v1/payments/{payment.id}/cash', headers=headers, json={}).status_code == 403
    assert client.get(f'/api/v1/inventory/summary/{b.id}', headers=headers).status_code == 403
    assert client.get(f'/api/v1/stocks/branch/{b.id}', headers=headers).status_code == 403
    assert client.get('/api/v1/payments', headers=users['unassigned']).status_code == 403
    branches = client.get('/api/v1/branches', headers=headers).json()
    assert [branch['id'] for branch in branches] == [a.id]
    matrix = client.get('/api/v1/stocks/matrix', headers=headers).json()
    assert matrix[0]['total_quantity'] == 3
    assert list(matrix[0]['branches']) == [a.id]
    products = client.get('/api/v1/products', headers=users['STORE_MANAGER']).json()
    assert products[0]['total_stock'] == 3
    assert all(stock['branch_id'] == a.id for stock in products[0]['variants'][0]['stocks'])


def test_business_audit_ignores_navigation_and_records_success_once(client, db_session, world):
    a, b, _, variant, _, users = world
    headers = users['ADMIN']
    db_session.add(Bitacora(user_name='Antes', user_email='old@test.local', action='NAVEGACION', description='Visita', category='SISTEMA', ip_address='127.0.0.1'))
    db_session.commit()
    client.get('/api/v1/products', headers=headers)
    assert client.post('/api/v1/activity-logs', headers=headers, json={'action': 'NAVEGACION', 'description': 'Visita'}).status_code == 405
    assert client.get('/api/v1/activity-logs', headers=headers).json()['total'] == 0
    invalid = client.post('/api/v1/branches', headers=headers, json={'name': '', 'city': '', 'address': ''})
    assert invalid.status_code == 422
    assert client.get('/api/v1/activity-logs', headers=headers).json()['total'] == 0
    created = client.post('/api/v1/inventory/movements', headers=headers, json={
        'branch_id': a.id, 'variant_id': variant.id, 'type': 'ENTRY', 'quantity': 2, 'reason': 'Ingreso de prueba'})
    assert created.status_code == 201
    logs = client.get('/api/v1/activity-logs', headers=headers).json()
    assert logs['total'] == 1
    assert logs['items'][0]['branch_id'] == a.id
    assert 'ip_address' not in logs['items'][0]
    deleted = client.delete(f"/api/v1/inventory/movements/{created.json()['id']}", headers=headers)
    assert deleted.status_code == 200
    logs = client.get('/api/v1/activity-logs', headers=headers, params={'action': 'ELIMINAR'}).json()
    assert logs['total'] == 1
    assert logs['items'][0]['branch_id'] == a.id
    assert client.get('/api/v1/activity-logs', headers=headers, params={'branch_id': b.id}).json()['total'] == 0
    assert client.get('/api/v1/activity-logs', headers=users['STORE_MANAGER'], params={'branch_id': b.id}).status_code == 403


def test_existing_sqlite_audit_schema_upgrades_without_losing_history():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE branches (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE activity_logs (id VARCHAR(36) PRIMARY KEY, description TEXT)'))
        conn.execute(text("INSERT INTO activity_logs VALUES ('old', 'Keep history')"))
    ensure_activity_scope_schema(engine)
    ensure_activity_scope_schema(engine)
    assert {'branch_id', 'branch_name'} <= {column['name'] for column in inspect(engine).get_columns('activity_logs')}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT description FROM activity_logs')).scalar() == 'Keep history'
