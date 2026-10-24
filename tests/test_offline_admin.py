import uuid
from unittest.mock import patch
import pytest
from tests.test_saas import companies, headers
from app.modelos import Producto, VarianteProducto, Stock, Usuario, Sucursal, Categoria
from app.modelos.operacion_sincronizacion import OperacionSincronizacion


def sync(client, user, path, body=None, method='POST', operation_id=None, expected=200):
    command = dict(operation_id=operation_id or str(uuid.uuid4()), account_id=user.id,
                   tenant_id=user.tenant_id, method=method, path=path, body=body or {})
    response = client.post('/api/v1/sync/operations', headers=headers(user), json=command)
    assert response.status_code == expected, response.text
    return command, response.json()


def local(command):
    return 'local-' + command['operation_id']


def test_complete_offline_dependency_chain_and_retries(client, db_session, companies):
    _, ((tenant_id, admin), _) = companies
    branch, b = sync(client, admin, '/branches', dict(name='Sucursal offline', city='El Alto', address='Av. Principal'))
    category, _ = sync(client, admin, '/attributes/categories', dict(name='Categoría offline'))
    size, _ = sync(client, admin, '/attributes/sizes', dict(name='Mediana', code='MOFF'))
    color, _ = sync(client, admin, '/attributes/colors', dict(name='Azul offline', hex_code='#123456'))
    supplier, _ = sync(client, admin, '/suppliers', dict(company_name='Proveedor offline', contact_name='Contacto nuevo', email='proveedor@example.com', phone='77777777'))
    season, _ = sync(client, admin, '/seasons', dict(name='Temporada offline', start_date='2026-01-01', end_date='2027-12-31'))
    promotion, _ = sync(client, admin, '/promotions', dict(name='Promoción offline', discount_percent=10, start_date='2026-01-01', end_date='2027-12-31'))
    product, p = sync(client, admin, '/products', dict(name='Prenda offline', price=100,
        category_id=local(category), supplier_id=local(supplier), season_id=local(season), promotion_id=local(promotion),
        variants=[dict(size_id=local(size), color_id=local(color), initial_stock={local(branch): 5})]))
    variant = local(product) + '-variant-0'
    assert p['_local_ids'][variant] == p['variants'][0]['id']
    movement, m = sync(client, admin, '/inventory/movements', dict(branch_id=local(branch), variant_id=variant, type='ENTRY', quantity=2, reason='Ingreso offline'))
    assert m['new_stock'] == 7
    retry = client.post('/api/v1/sync/operations', headers=headers(admin), json=movement)
    assert retry.status_code == 200 and retry.json() == m
    assert db_session.query(Stock).one().quantity == 7
    _, payment = sync(client, admin, '/payments/offline-sale', dict(branch_id=local(branch), customer_name='Cliente offline', amount=90, concept='Venta offline', payment_type='EFECTIVO', items=[dict(variant_id=variant, quantity=1, unit_price=90, product_name='Prenda offline')]))
    assert payment['status'] == 'PAID'
    assert db_session.query(Stock).one().quantity == 6
    _, employee = sync(client, admin, '/users', dict(email='personal-offline@example.com', password='StrongPass123!', full_name='Empleado nuevo', role='CASHIER', branch_id=local(branch)))
    assert employee['branch_id'] == b['id']
    assert 'password' not in str(employee) and 'hashed_password' not in str(employee)
    _, profile = sync(client, admin, '/users/me', {'full_name': 'Administrador actualizado'}, 'PUT')
    assert profile['id'] == admin.id and profile['full_name'] == 'Administrador actualizado'
    _, edited = sync(client, admin, '/products/' + local(product), {'description': 'Descripción nueva'}, 'PUT')
    assert edited['id'] == p['id'] and edited['description'] == 'Descripción nueva'
    _, toggled = sync(client, admin, '/attributes/categories/' + local(category) + '/toggle-status', {}, 'PATCH')
    assert toggled['is_active'] is False


def test_failed_dependency_and_cross_company_references_do_not_write(client, db_session, companies):
    _, ((tenant, admin), (_, other)) = companies
    _, foreign = sync(client, other, '/attributes/categories', {'name': 'Categoría ajena'})
    before = db_session.query(Producto).execution_options(skip_tenant=True).count()
    sync(client, admin, '/products', dict(name='No válida', price=20, category_id=foreign['id']), expected=404)
    sync(client, admin, '/products', dict(name='Pendiente', price=20, category_id='local-' + str(uuid.uuid4())), expected=424)
    assert db_session.query(Producto).execution_options(skip_tenant=True).count() == before


def test_local_branches_enforce_plan_and_non_admin_cannot_create_staff(client, db_session, companies):
    _, ((_, admin), _) = companies
    for name in ('Sucursal uno', 'Sucursal dos'):
        sync(client, admin, '/branches', dict(name=name, city='La Paz', address='Av. Principal'))
    sync(client, admin, '/branches', dict(name='Sucursal tres', city='La Paz', address='Av. Principal'), expected=409)
    admin.role = 'CASHIER'
    db_session.commit()
    sync(client, admin, '/users', dict(email='no@example.com', full_name='No permitido', password='StrongPass123!', role='ADMIN'), expected=403)


def test_product_failure_rolls_back_entire_operation_and_receipt(client, db_session, companies):
    _, ((_, admin), _) = companies
    category, _ = sync(client, admin, '/attributes/categories', {'name': 'Categoría para rollback'})
    before = db_session.query(OperacionSincronizacion).count()
    with patch('app.api.v1.productos.BitacoraService.log_event', side_effect=RuntimeError('failed audit')):
        with pytest.raises(RuntimeError):
            sync(client, admin, '/products', dict(name='Producto revertido', price=20, category_id=local(category)))
    assert db_session.query(Producto).count() == 0
    assert db_session.query(OperacionSincronizacion).count() == before


def test_missing_stock_baseline_is_rejected(client, companies):
    _, ((_, admin), _) = companies
    sync(client, admin, '/stocks/adjust', dict(branch_id='missing', variant_id='missing', quantity=0), expected=403)
