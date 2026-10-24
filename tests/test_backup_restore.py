import copy
import gzip
import json
import uuid
import pytest
from sqlalchemy import event
from tests.test_saas import companies, headers, create_branch, seed_product
from app.base_datos import Base
from app.modelos import Producto, VarianteProducto, Stock, Categoria
from app.configuracion import settings


@pytest.fixture
def saved(client, db_session, companies, monkeypatch, tmp_path):
    root, ((tenant, admin), (other_tenant, other)) = companies
    monkeypatch.setattr(settings, 'BACKUP_DIR', str(tmp_path))
    branch = create_branch(client, admin).json()['id']
    product, variant = seed_product(db_session, tenant, branch)
    ids = dict(product=product.id, variant=variant.id, branch=branch, category=product.category_id)
    record = client.post('/api/v1/backups', headers=headers(admin)).json()
    response = client.get('/api/v1/backups/' + record['id'] + '/download', headers=headers(admin))
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['content-disposition'].endswith('.json"')
    return dict(root=root, admin=admin, tenant=tenant, other=other, content=response.content, payload=response.json(), ids=ids)


def review(client, saved, content=None, user=None, expected=200):
    response = client.post('/api/v1/backups/preview', params={'tenant_id': saved['tenant']}, headers=headers(user or saved['admin']), content=content or saved['content'])
    assert response.status_code == expected, response.text
    return response.json()


def restore(client, saved, preview, content=None, expected=200):
    response = client.post('/api/v1/backups/restore', params={'tenant_id': saved['tenant']}, headers={**headers(saved['admin']), 'X-Vesta-Backup-Review': preview['review_token']}, content=content or saved['content'])
    assert response.status_code == expected, response.text
    return response.json()


def delete_catalog(db, ids):
    for name, column, value in [('stocks', 'variant_id', ids['variant']), ('product_variants', 'id', ids['variant']), ('products', 'id', ids['product'])]:
        table = Base.metadata.tables[name]
        db.connection().execute(table.delete().where(table.c[column] == value))
    db.commit()
    db.expire_all()


def test_review_does_not_write_and_restore_recovers_deleted_catalog_once(client, db_session, saved):
    delete_catalog(db_session, saved['ids'])
    preview = review(client, saved)
    assert preview['missing'] >= 3
    assert db_session.query(Producto).count() == 0
    result = restore(client, saved, preview)
    assert result['restored'] >= 3
    assert db_session.get(Producto, saved['ids']['product']) is not None
    assert db_session.get(VarianteProducto, saved['ids']['variant']) is not None
    assert db_session.query(Stock).count() == 1
    second = review(client, saved)
    assert second['missing'] == 0
    assert restore(client, saved, second)['restored'] == 0
    assert db_session.query(Producto).count() == 1


def test_existing_records_and_current_stock_are_never_overwritten(client, db_session, saved):
    product = db_session.get(Producto, saved['ids']['product'])
    product.price = 999
    stock = db_session.query(Stock).one()
    stock.quantity = 2
    db_session.commit()
    preview = review(client, saved)
    assert preview['missing'] == 0
    restore(client, saved, preview)
    db_session.expire_all()
    assert float(db_session.get(Producto, product.id).price) == 999
    assert db_session.query(Stock).one().quantity == 2


def test_duplicate_natural_keys_are_reused_for_restored_relationships(client, db_session, saved):
    delete_catalog(db_session, saved['ids'])
    payload = copy.deepcopy(saved['payload'])
    category = payload['tables']['categories'][0]
    old_id = category['id']
    category['id'] = str(uuid.uuid4())
    payload['tables']['products'][0]['category_id'] = category['id']
    content = json.dumps(payload).encode()
    preview = review(client, saved, content)
    restore(client, saved, preview, content)
    assert db_session.query(Categoria).count() == 1
    assert db_session.get(Producto, saved['ids']['product']).category_id == old_id


def test_other_company_and_unreviewed_or_changed_files_are_rejected(client, db_session, saved):
    review(client, saved, user=saved['other'], expected=403)
    payload = copy.deepcopy(saved['payload']); payload['tenant_id'] = str(uuid.uuid4())
    review(client, saved, json.dumps(payload).encode(), expected=422)
    delete_catalog(db_session, saved['ids'])
    preview = review(client, saved)
    payload = copy.deepcopy(saved['payload']); payload['tables']['products'][0]['name'] = 'Alterada'
    restore(client, saved, preview, json.dumps(payload).encode(), expected=409)
    response = client.post('/api/v1/backups/restore', headers=headers(saved['admin']), content=saved['content'])
    assert response.status_code == 409
    assert db_session.query(Producto).count() == 0


def test_missing_dependencies_are_reported_without_partial_invalid_inserts(client, db_session, saved):
    delete_catalog(db_session, saved['ids'])
    payload = copy.deepcopy(saved['payload'])
    payload['tables']['products'][0]['category_id'] = str(uuid.uuid4())
    content = json.dumps(payload).encode()
    preview = review(client, saved, content)
    assert preview['issues'] and preview['missing'] == 0
    restore(client, saved, preview, content)
    assert db_session.query(Producto).count() == 0


def test_old_gzip_and_invalid_json_handling(client, saved):
    assert review(client, saved, gzip.compress(saved['content']))['missing'] == 0
    review(client, saved, b'not json', expected=422)
    review(client, saved, b'{"format":"VESTA_COMPANY_BACKUP","format":"bad"}', expected=422)


def test_duplicate_product_names_with_different_ids_are_not_inserted(client, db_session, saved):
    payload = copy.deepcopy(saved['payload'])
    payload['tables']['products'][0]['id'] = str(uuid.uuid4())
    payload['tables']['products'][0]['name'] = '  ' + payload['tables']['products'][0]['name'].upper() + '  '
    content = json.dumps(payload).encode()
    preview = review(client, saved, content)
    assert preview['missing'] == 0
    restore(client, saved, preview, content)
    assert db_session.query(Producto).count() == 1


def test_recovery_includes_deleted_catalog_dependencies(client, db_session, saved):
    delete_catalog(db_session, saved['ids'])
    for name in ('categories', 'sizes', 'colors'):
        table = Base.metadata.tables[name]
        db_session.connection().execute(table.delete().where(table.c.tenant_id == saved['tenant']))
    db_session.commit()
    preview = review(client, saved)
    assert preview['missing'] >= 6
    restore(client, saved, preview)
    variant = db_session.get(VarianteProducto, saved['ids']['variant'])
    assert variant.size is not None and variant.color is not None
    assert db_session.get(Producto, saved['ids']['product']).category is not None


def test_stale_review_is_rejected_without_writing(client, db_session, saved):
    delete_catalog(db_session, saved['ids'])
    preview = review(client, saved)
    category = db_session.get(Categoria, saved['ids']['category'])
    db_session.connection().execute(Categoria.__table__.delete().where(Categoria.id == category.id))
    db_session.commit()
    restore(client, saved, preview, expected=409)
    assert db_session.query(Producto).count() == 0


def test_failure_during_restore_rolls_back_the_whole_catalog(client, db_session, saved):
    delete_catalog(db_session, saved['ids'])
    preview = review(client, saved)
    engine = db_session.get_bind()
    def fail_on_stock(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO stocks'):
            raise RuntimeError('simulated storage failure')
    event.listen(engine, 'before_cursor_execute', fail_on_stock)
    try:
        with pytest.raises(RuntimeError):
            restore(client, saved, preview)
    finally:
        event.remove(engine, 'before_cursor_execute', fail_on_stock)
    assert db_session.query(Producto).count() == 0
    assert db_session.query(VarianteProducto).count() == 0
    assert db_session.query(Stock).count() == 0
