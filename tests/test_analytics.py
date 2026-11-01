from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pytest

from app.modelos import Producto, Usuario, Stock, Pago, Reserva, Sucursal
from app.modelos.analitica import ConjuntoSintetico, EntrenamientoModelo
from app.modelos.movimiento_inventario import MovimientoInventario
from app.esquemas.analitica import GenerarSinteticosRequest
from app.servicios.datos_sinteticos_service import decode, generate
from tests.test_saas import companies, headers


def generation_payload(**changes):
    return {'request_id': str(uuid4()), 'name': 'Prueba de temporada', 'date_from': '2025-01-01',
            'date_to': '2025-12-31', 'customers': 40, 'products': 10, 'sales': 800, 'seed': 42, **changes}


def make_dataset(client, companies):
    root, ((tenant, admin), _) = companies
    payload = generation_payload()
    response = client.post(f'/api/v1/saas/companies/{tenant}/synthetic-data', headers=headers(root), json=payload)
    assert response.status_code == 201, response.text
    return tenant, admin, response.json(), payload


def test_generation_is_reproducible_prepared_and_has_commercial_patterns():
    parameters = GenerarSinteticosRequest(**generation_payload(sales=5000, customers=100, products=20))
    data, preprocessing, summary = generate(parameters, ['Centro', 'Sur'])
    second, _, same_summary = generate(parameters, ['Centro', 'Sur'])
    assert data == second and summary == same_summary
    raw, prepared = data['raw'], data['prepared']
    assert len(raw['sales']) == 5000 and summary['returns'] > 0 and summary['injected_anomalies'] == 150
    assert len({row['profile'] for row in raw['customers']}) == 3
    weekends = sum(date.fromisoformat(row['date']).weekday() >= 5 for row in raw['sales'])
    assert weekends / len(raw['sales']) > .35
    winter_coats = sum(row['category'] == 'Abrigos' and date.fromisoformat(row['date']).month in (5,6,7,8) for row in raw['sales'])
    summer_coats = sum(row['category'] == 'Abrigos' and date.fromisoformat(row['date']).month not in (5,6,7,8) for row in raw['sales'])
    assert winter_coats > summer_coats
    transformers = decode(preprocessing)
    demand = prepared['demand']
    train = [row for row in demand if row['split'] == 'train']
    test = [row for row in demand if row['split'] == 'test']
    assert max(row['week'] for row in train) < min(row['week'] for row in test)
    expected_mean = transformers['encoder'].transform([r['features'] for r in train]).mean(axis=0)
    np.testing.assert_allclose(transformers['demand_scaler'].mean_, expected_mean)
    assert 'injected_anomaly' not in transformers['anomaly_features']
    assert np.isfinite(np.array(prepared['anomaly_matrix'])).all()


def test_generation_does_not_change_real_operations_and_is_idempotent(client, db_session, companies):
    models = [Usuario, Producto, Stock, Pago, Reserva, MovimientoInventario]
    before = {model.__name__: db_session.query(model).execution_options(skip_tenant=True).count() for model in models}
    tenant, admin, data, payload = make_dataset(client, companies)
    again = client.post(f'/api/v1/saas/companies/{tenant}/synthetic-data', headers=headers(companies[0]), json=payload)
    assert again.json()['id'] == data['id']
    changed = {**payload, 'sales': 900}
    assert client.post(f'/api/v1/saas/companies/{tenant}/synthetic-data', headers=headers(companies[0]), json=changed).status_code == 409
    for model in models:
        assert db_session.query(model).execution_options(skip_tenant=True).count() == before[model.__name__]
    response = client.get('/api/v1/analytics/datasets', headers=headers(admin))
    assert response.status_code == 200 and response.json()[0]['id'] == data['id']
    assert datetime.fromisoformat(response.json()[0]['created_at']).utcoffset() == timedelta(0)
    assert 'payload' not in response.json()[0] and 'preprocessing' not in response.json()[0]
    download = client.get(f"/api/v1/analytics/datasets/{data['id']}/download", headers=headers(admin))
    assert download.status_code == 200 and len(download.json()['raw']['sales']) == 800
    assert download.json()['tenant_id'] == tenant


def test_generation_and_training_permissions_are_enforced(client, db_session, companies):
    root, ((tenant, admin), (_, other_admin)) = companies
    payload = generation_payload()
    assert client.post(f'/api/v1/saas/companies/{tenant}/synthetic-data', headers=headers(admin), json=payload).status_code == 403
    assert client.get(f'/api/v1/analytics/datasets?tenant_id={tenant}', headers=headers(other_admin)).status_code == 403
    for role in ('STORE_MANAGER', 'CASHIER', 'CUSTOMER'):
        db_session.info.clear()
        user = Usuario(email=role+'@analytics.test', full_name='No administrador', hashed_password='unused',
                       role=role, tenant_id=tenant, is_active=True)
        db_session.add(user); db_session.commit()
        assert client.get('/api/v1/analytics/datasets', headers=headers(user)).status_code == 403


def test_train_evaluates_real_models_and_saved_model_can_predict(client, db_session, companies):
    tenant, admin, data, _ = make_dataset(client, companies)
    request = {'request_id': str(uuid4()), 'dataset_id': data['id'], 'clusters': 3}
    response = client.post('/api/v1/analytics/train', headers=headers(admin), json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'COMPLETED', result
    assert set(result['metrics']['demand']) >= {'mae', 'rmse', 'r2', 'baseline_mae'}
    assert result['metrics']['demand']['train_until'] < result['metrics']['demand']['test_from']
    assert -1 <= result['metrics']['clustering']['silhouette'] <= 1
    assert 0 <= result['metrics']['anomalies']['f1'] <= 1
    run = db_session.get(EntrenamientoModelo, result['id'])
    bundle = decode(run.artifact)
    assert bundle['demand'].__class__.__name__ == 'RandomForestRegressor'
    assert bundle['clustering'].__class__.__name__ == 'KMeans'
    assert bundle['anomalies'].__class__.__name__ == 'IsolationForest'
    assert bundle['tenant_id'] == tenant
    again = client.post('/api/v1/analytics/train', headers=headers(admin), json=request)
    assert again.json()['id'] == result['id'] and db_session.query(EntrenamientoModelo).count() == 1
    assert client.post('/api/v1/analytics/train', headers=headers(admin), json={**request, 'clusters': 2}).status_code == 409
    detail = client.get('/api/v1/analytics/runs/'+run.id, headers=headers(admin)).json()
    assert sum(group['customers'] for group in detail['results']['groups']) == data['summary']['customers_with_purchases']
    example = detail['results']['forecasts'][0]
    inference = client.post(f'/api/v1/analytics/runs/{run.id}/predict', headers=headers(admin),
                            json={key: example[key] for key in ('week', 'category', 'branch')})
    assert inference.status_code == 200 and inference.json()['predicted_units'] == example['predicted_units']
    run.artifact = b'corrupted'; db_session.commit()
    assert client.post(f'/api/v1/analytics/runs/{run.id}/predict', headers=headers(admin),
                      json={key: example[key] for key in ('week', 'category', 'branch')}).status_code == 409


def test_dataset_and_models_never_cross_tenant_boundary(client, db_session, companies):
    tenant, admin, data, _ = make_dataset(client, companies)
    root, (_, (other, other_admin)) = companies
    assert client.get('/api/v1/analytics/datasets', headers=headers(other_admin)).json() == []
    assert client.get(f"/api/v1/analytics/datasets/{data['id']}/download", headers=headers(other_admin)).status_code == 404
    request = {'request_id': str(uuid4()), 'dataset_id': data['id'], 'clusters': 3}
    assert client.post('/api/v1/analytics/train', headers=headers(other_admin), json=request).status_code == 404
    result = client.post(f'/api/v1/analytics/train?tenant_id={tenant}', headers=headers(root), json=request).json()
    assert result['status'] == 'COMPLETED' and result['tenant_id'] == tenant
    assert client.get('/api/v1/analytics/runs/'+result['id'], headers=headers(other_admin)).status_code == 404
    assert client.get('/api/v1/analytics/runs', headers=headers(other_admin)).json() == []


def test_failed_and_interrupted_training_remains_reviewable(client, db_session, companies, monkeypatch):
    tenant, admin, data, _ = make_dataset(client, companies)
    from app.servicios import entrenamiento_service
    def fail(*args):
        raise ValueError('Controlled test failure')
    monkeypatch.setattr(entrenamiento_service, 'train_models', fail)
    request = {'request_id': str(uuid4()), 'dataset_id': data['id'], 'clusters': 3}
    response = client.post('/api/v1/analytics/train', headers=headers(admin), json=request)
    assert response.json()['status'] == 'FAILED' and response.json()['error']
    stale = EntrenamientoModelo(tenant_id=tenant, request_id=str(uuid4()), dataset_id=data['id'], created_by=admin.id,
                                parameters={}, status='TRAINING', created_at=datetime.now(timezone.utc)-timedelta(minutes=20))
    db_session.add(stale); db_session.commit()
    rows = client.get('/api/v1/analytics/runs', headers=headers(admin)).json()
    recovered = next(row for row in rows if row['id'] == stale.id)
    assert recovered['status'] == 'FAILED' and '15 minutos' in recovered['error']


def test_input_limits_and_active_training_conflict(client, db_session, companies):
    tenant, admin, data, _ = make_dataset(client, companies)
    root = companies[0]
    for change in ({'date_to': '2024-12-01'}, {'sales': 20001}, {'customers': 3}, {'name': '  '}):
        assert client.post(f'/api/v1/saas/companies/{tenant}/synthetic-data', headers=headers(root),
                           json=generation_payload(**change)).status_code == 422
    row = EntrenamientoModelo(tenant_id=tenant, request_id=str(uuid4()), dataset_id=data['id'], created_by=admin.id,
                              parameters={}, status='TRAINING')
    db_session.info.update(tenant_id=tenant)
    db_session.add(row); db_session.commit()
    request = {'request_id': str(uuid4()), 'dataset_id': data['id'], 'clusters': 3}
    assert client.post('/api/v1/analytics/train', headers=headers(admin), json=request).status_code == 409


def test_analytics_artifacts_do_not_break_business_backup(client, db_session, companies, monkeypatch, tmp_path):
    tenant, admin, data, _ = make_dataset(client, companies)
    from app.configuracion import settings
    from app.servicios.respaldo_service import create_backup
    monkeypatch.setattr(settings, 'BACKUP_DIR', str(tmp_path))
    manifest = create_backup(tenant, bind=db_session.get_bind())
    assert 'analytics_datasets' not in manifest['tables'] and 'analytics_runs' not in manifest['tables']


def test_additive_migration_preserves_existing_tables(monkeypatch):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect, select
    from app.base_datos import Base
    from app.modelos.saas import Empresa
    from alembic import op
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/2026_11_01_0100-analytics_models.py'
    spec = importlib.util.spec_from_file_location('analytics_migration', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        EntrenamientoModelo.__table__.drop(conn)
        ConjuntoSintetico.__table__.drop(conn)
        conn.execute(Empresa.__table__.insert().values(id='existing', name='Conservar', slug='conservar'))
        monkeypatch.setattr(op, 'get_bind', lambda: conn)
        migration.upgrade(); migration.upgrade()
        assert {'analytics_datasets','analytics_runs'} <= set(inspect(conn).get_table_names())
        assert 'uq_analytics_active_run' in {index['name'] for index in inspect(conn).get_indexes('analytics_runs')}
        assert conn.execute(select(Empresa.name)).scalar() == 'Conservar'
    engine.dispose()


def test_synthetic_branches_keep_same_name_in_different_cities_separate(client, db_session, companies):
    root, ((tenant, _), _) = companies
    db_session.info.clear()
    db_session.add_all([Sucursal(tenant_id=tenant, name='Centro', city='La Paz', address='Prueba 1'),
                        Sucursal(tenant_id=tenant, name='Centro', city='El Alto', address='Prueba 2')])
    db_session.commit()
    response = client.post(f'/api/v1/saas/companies/{tenant}/synthetic-data', headers=headers(root), json=generation_payload())
    assert response.status_code == 201, response.text
    assert set(response.json()['summary']['branches']) == {'Centro · La Paz', 'Centro · El Alto'}
