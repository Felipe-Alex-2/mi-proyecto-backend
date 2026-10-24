import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text, inspect
from tests.test_saas import companies, headers
from app.nucleo.ubicaciones_bolivia import LOCATIONS
from app.nucleo.esquema_saas import ensure_company_department
from app.modelos.saas import Empresa


def test_catalog_has_nine_departments_and_same_frontend_options():
    assert set(LOCATIONS) == {'La Paz', 'Santa Cruz', 'Cochabamba', 'Oruro', 'Potosí',
                              'Chuquisaca', 'Beni', 'Pando', 'Tarija'}
    source = (Path(__file__).parents[2] / 'web/src/app/nucleo/datos/ubicaciones-bolivia.ts').read_text(encoding='utf-8')
    payload = source.split(' = ', 1)[1].split(';\nexport const BOLIVIA_DEPARTMENTS', 1)[0]
    assert json.loads(payload) == LOCATIONS
    assert 'El Alto' in LOCATIONS['La Paz']
    assert 'Sucre' in LOCATIONS['Chuquisaca']
    assert 'Trinidad' in LOCATIONS['Beni']
    assert 'Cobija' in LOCATIONS['Pando']


@pytest.mark.parametrize('department', [None, '', 'Sucre', 'Lima'])
def test_company_requires_valid_department(client, companies, department):
    root, _ = companies
    payload = dict(name='Nueva empresa', slug='nueva-empresa', admin_name='Admin nuevo',
                   admin_email='nuevo@example.com', admin_password='Company123!')
    if department is not None:
        payload['department'] = department
    assert client.post('/api/v1/saas/companies', headers=headers(root), json=payload).status_code == 422


def test_department_persists_and_restricts_branch_create_and_update(client, companies, db_session):
    root, ((company_id, admin), _) = companies
    assert db_session.get(Empresa, company_id).department == 'La Paz'
    assert client.get('/api/v1/saas/subscription', headers=headers(admin)).json()['department'] == 'La Paz'
    payload = dict(name='Sucursal Centro', city='Santa Cruz de la Sierra', address='Av. Principal')
    assert client.post('/api/v1/branches', headers=headers(admin), json=payload).status_code == 422
    payload['city'] = 'el alto'
    response = client.post('/api/v1/branches', headers=headers(admin), json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['city'] == 'El Alto'
    branch_id = response.json()['id']
    assert client.put('/api/v1/branches/' + branch_id, headers=headers(admin), json={'city': 'Sucre'}).status_code == 422
    assert client.get('/api/v1/branches/' + branch_id, headers=headers(admin)).json()['city'] == 'El Alto'


def test_legacy_company_assignment_is_platform_only_and_preserves_branches(client, companies, db_session):
    root, ((company_id, admin), _) = companies
    company = db_session.get(Empresa, company_id)
    company.department = None
    db_session.commit()
    payload = dict(name='Sucursal Centro', city='La Paz', address='Av. Principal')
    assert client.post('/api/v1/branches', headers=headers(admin), json=payload).status_code == 400
    url = '/api/v1/saas/companies/' + company_id + '/department'
    assert client.patch(url, headers=headers(admin), json={'department': 'La Paz'}).status_code == 403
    response = client.patch(url, headers=headers(root), json={'department': 'la paz'})
    assert response.status_code == 200, response.text
    assert response.json()['department'] == 'La Paz'
    assert client.post('/api/v1/branches', headers=headers(admin), json=payload).status_code == 201
    assert client.patch(url, headers=headers(root), json={'department': 'Beni'}).status_code == 409


def test_department_migration_is_idempotent_without_guessing_existing_locations():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT)'))
        conn.execute(text("INSERT INTO tenants VALUES ('old', 'Existing company')"))
        ensure_company_department(conn)
        ensure_company_department(conn)
        assert 'department' in {column['name'] for column in inspect(conn).get_columns('tenants')}
        assert conn.execute(text("SELECT department FROM tenants WHERE id='old'")).scalar() is None
