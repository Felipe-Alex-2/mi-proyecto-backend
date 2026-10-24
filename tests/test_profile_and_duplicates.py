import base64
import importlib.util
import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize('avatar', ['terracotta', 'sage', 'sand'])
def test_avatar_is_persisted_and_returned_after_login(client, admin_token, db_session, avatar):
    headers = {'Authorization': f'Bearer {admin_token}'}
    result = client.put('/api/v1/users/me', headers=headers, json={'avatar_id': avatar, 'profile_photo': None})
    assert result.status_code == 200
    db_session.expire_all()
    assert client.get('/api/v1/users/me', headers=headers).json()['avatar_id'] == avatar
    login = client.post('/api/v1/auth/login', json={'email': 'admin_fixture@example.com', 'password': 'Password123!'})
    assert login.json()['user']['avatar_id'] == avatar


def test_photo_is_normalized_persisted_and_can_be_replaced_by_avatar(client, admin_token, db_session):
    image = Image.new('RGB', (900, 600), '#DCE5DB')
    buffer = io.BytesIO(); image.save(buffer, 'PNG')
    photo = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    headers = {'Authorization': f'Bearer {admin_token}'}
    response = client.put('/api/v1/users/me', headers=headers, json={'profile_photo': photo})
    assert response.status_code == 200
    stored = response.json()['profile_photo']
    assert stored.startswith('data:image/jpeg;base64,')
    with Image.open(io.BytesIO(base64.b64decode(stored.split(',')[1]))) as normalized:
        assert max(normalized.size) == 512
    db_session.expire_all()
    assert client.get('/api/v1/users/me', headers=headers).json()['profile_photo'] == stored
    # A text-only update must preserve the photo; explicit null clears it.
    assert client.put('/api/v1/users/me', headers=headers, json={'full_name': 'Nuevo Nombre'}).json()['profile_photo'] == stored
    result = client.put('/api/v1/users/me', headers=headers, json={'avatar_id': 'sage', 'profile_photo': None})
    assert result.json()['profile_photo'] is None
    assert result.json()['avatar_id'] == 'sage'


@pytest.mark.parametrize('payload', [
    {'full_name': ''}, {'full_name': '  '}, {'full_name': ' a '},
    {'email': ''}, {'avatar_id': ''}, {'avatar_id': 'unknown'},
    {'profile_photo': ''}, {'profile_photo': 'https://example.com/photo.jpg'},
    {'profile_photo': 'data:image/svg+xml;base64,PHN2Zz4='},
    {'profile_photo': 'data:image/png;base64,bm90LWFuLWltYWdl'},
])
def test_invalid_profile_input_is_rejected_without_modifying_user(client, admin_token, payload):
    headers = {'Authorization': f'Bearer {admin_token}'}
    before = client.get('/api/v1/users/me', headers=headers).json()
    assert client.put('/api/v1/users/me', headers=headers, json=payload).status_code == 422
    after = client.get('/api/v1/users/me', headers=headers).json()
    assert after == before


def test_category_duplicates_use_literal_case_insensitive_names(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    assert client.post('/api/v1/attributes/categories', headers=headers, json={'name': 'Prenda ABC'}).status_code == 201
    # Percent signs are literal names, not SQL LIKE wildcards.
    assert client.post('/api/v1/attributes/categories', headers=headers, json={'name': 'Prenda %'}).status_code == 201
    assert client.post('/api/v1/attributes/categories', headers=headers, json={'name': '  prenda %  '}).status_code == 409


def test_duplicate_variants_and_negative_initial_stock_return_validation_errors(client, admin_token, db_session):
    from app.modelos.categoria import Categoria
    from app.modelos.color import Color
    from app.modelos.talla import Talla
    category = Categoria(name='Prendas test'); color = Color(name='Crema', hex_code='#FAF7F2'); size = Talla(name='Mediana', code='M')
    db_session.add_all([category, color, size]); db_session.commit()
    variant = {'size_id': size.id, 'color_id': color.id}
    payload = {'name': 'Blusa test', 'price': 29, 'category_id': category.id, 'variants': [variant, variant]}
    headers = {'Authorization': f'Bearer {admin_token}'}
    assert client.post('/api/v1/products', headers=headers, json=payload).status_code == 422
    payload['variants'] = [{**variant, 'initial_stock': {'branch': -1}}]
    assert client.post('/api/v1/products', headers=headers, json=payload).status_code == 422
    assert client.get('/api/v1/products', headers=headers).json() == []


@pytest.mark.parametrize('endpoint', ['seasons', 'promotions'])
def test_partial_date_updates_respect_existing_date_range(client, admin_token, endpoint):
    headers = {'Authorization': f'Bearer {admin_token}'}
    data = {'name': 'Temporada de prueba', 'start_date': '2027-01-01', 'end_date': '2027-02-01'}
    if endpoint == 'promotions': data['discount_percent'] = 10
    created = client.post(f'/api/v1/{endpoint}', headers=headers, json=data)
    assert created.status_code == 201
    url = f"/api/v1/{endpoint}/{created.json()['id']}"
    assert client.put(url, headers=headers, json={'start_date': '2027-03-01'}).status_code == 422
    assert client.get(url, headers=headers).json()['start_date'] == '2027-01-01'


def test_profile_migration_preserves_existing_users_and_is_idempotent():
    path = Path(__file__).parents[1] / 'alembic/versions/2026_10_13_2300-profile_avatars.py'
    spec = importlib.util.spec_from_file_location('profile_migration', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id VARCHAR PRIMARY KEY, full_name VARCHAR NOT NULL)'))
        connection.execute(text("INSERT INTO users VALUES ('old', 'Existing Usuario')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade(); migration.upgrade()
        assert {'avatar_id', 'profile_photo'} <= {c['name'] for c in inspect(connection).get_columns('users')}
        row = connection.execute(text('SELECT full_name, avatar_id, profile_photo FROM users')).one()
        assert tuple(row) == ('Existing Usuario', 'terracotta', None)
    engine.dispose()
