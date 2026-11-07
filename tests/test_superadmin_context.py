"""Server-owned superadmin switching and ordinary staff isolation."""
import pytest
from sqlalchemy import select
from app.modelos import Usuario
from app.modelos.bitacora import Bitacora
from app.modelos.saas import ClienteEmpresa, Empresa
from app.nucleo.seguridad import get_password_hash
from tests.test_saas import companies, headers, create_branch


def test_platform_switch_scopes_reads_writes_and_audit(client, db_session, companies):
    root, ((a, admin_a), (b, admin_b)) = companies
    ba = create_branch(client, admin_a).json()['id']
    bb = create_branch(client, admin_b).json()['id']
    auth = headers(root)
    for tenant, branch, label in [(a, ba, 'Solo A'), (b, bb, 'Solo B')]:
        switched = client.put('/api/v1/saas/selection', headers=auth,
                              json={'tenant_id': tenant, 'branch_id': branch})
        assert switched.status_code == 200, switched.text
        assert switched.json()['tenant_id'] == tenant
        assert switched.json()['selected_tenant_id'] == tenant
        assert switched.json()['branch_id'] == branch
        assert switched.json()['is_saas_admin'] is True
        assert switched.json()['branch_name'] == 'Centro'
        assert switched.json()['company_name'] == ('moda-a' if tenant == a else 'moda-b')
        profile = client.get('/api/v1/users/me', headers=auth).json()
        assert profile['tenant_id'] == tenant
        assert profile['branch_id'] == branch
        rows = client.get('/api/v1/branches', headers=auth).json()
        assert [row['id'] for row in rows] == [branch]
        created = client.post('/api/v1/attributes/categories', headers=auth, json={'name': label})
        assert created.status_code == 201, created.text
        rows = client.get('/api/v1/attributes/categories', headers=auth).json()
        assert [row['name'] for row in rows] == [label]
        assert client.get('/api/v1/saas/companies', headers=auth).status_code == 200
    assert client.get('/api/v1/branches/' + ba, headers=auth).status_code == 404
    # The client cannot bypass the persisted staff scope using a tenant header.
    assert client.get('/api/v1/branches', headers={**auth, 'X-Vesta-Empresa': a,
                      'X-Vesta-Sucursal': ba}).status_code == 403
    db_session.info.clear()
    assert db_session.execute(select(ClienteEmpresa).where(ClienteEmpresa.user_id == root.id)).scalars().all() == []
    logs = db_session.execute(select(Bitacora).where(
        Bitacora.user_id == root.id, Bitacora.action == 'CAMBIAR_CONTEXTO_EMPRESA')).scalars().all()
    assert {(log.tenant_id, log.branch_id) for log in logs} == {(a, ba), (b, bb)}


@pytest.mark.parametrize('role', ['ADMIN', 'STORE_MANAGER', 'CASHIER'])
def test_staff_cannot_switch_company(client, db_session, companies, role):
    _, ((a, admin_a), (b, admin_b)) = companies
    ba = create_branch(client, admin_a).json()['id']
    bb = create_branch(client, admin_b).json()['id']
    db_session.info.clear()
    staff = Usuario(email=role.lower() + '@example.com', full_name='Staff', role=role,
                    tenant_id=a, selected_tenant_id=a, branch_id=ba,
                    hashed_password=get_password_hash('Staff123!'))
    db_session.add(staff)
    db_session.commit()
    result = client.put('/api/v1/saas/selection', headers=headers(staff),
                        json={'tenant_id': b, 'branch_id': bb})
    assert result.status_code == 403
    db_session.refresh(staff)
    assert (staff.tenant_id, staff.branch_id) == (a, ba)


def test_invalid_selection_preserves_platform_context(client, db_session, companies):
    root, ((a, admin_a), (b, admin_b)) = companies
    ba = create_branch(client, admin_a).json()['id']
    bb = create_branch(client, admin_b).json()['id']
    auth = headers(root)
    assert client.put('/api/v1/saas/selection', headers=auth,
                      json={'tenant_id': a, 'branch_id': ba}).status_code == 200
    for tenant, branch in [(b, ba), (a, 'missing'), ('missing', bb)]:
        assert client.put('/api/v1/saas/selection', headers=auth,
                          json={'tenant_id': tenant, 'branch_id': branch}).status_code == 422
    db_session.info.clear()
    db_session.get(Empresa, b).is_active = False
    db_session.commit()
    assert client.put('/api/v1/saas/selection', headers=auth,
                      json={'tenant_id': b, 'branch_id': bb}).status_code == 422
    me = client.get('/api/v1/users/me', headers=auth).json()
    assert (me['tenant_id'], me['branch_id']) == (a, ba)


def test_company_admin_cannot_modify_platform_account_after_switch(client, db_session, companies):
    root, ((a, admin_a), _) = companies
    branch = create_branch(client, admin_a).json()['id']
    assert client.put('/api/v1/saas/selection', headers=headers(root),
                      json={'tenant_id': a, 'branch_id': branch}).status_code == 200
    assert client.put('/api/v1/users/' + root.id, headers=headers(admin_a),
                      json={'full_name': 'Intrusion'}).status_code == 403
    assert client.patch('/api/v1/users/' + root.id + '/toggle-status',
                        headers=headers(admin_a)).status_code == 403
