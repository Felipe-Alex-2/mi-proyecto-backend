import io
import threading
from contextlib import contextmanager

import pytest
from sqlalchemy import event
from starlette.datastructures import UploadFile

from app.models.branch import Branch
from app.models.cart_item import CartItem
from app.models.category import Category
from app.models.color import Color
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.size import Size
from app.models.stock import Stock
from app.models.user import User
from app.services.cart_service import CartService
from app.services.catalog_service import CatalogService
from app.services.product_service import ProductService


@contextmanager
def count_selects(session):
    statements = []
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    engine = session.get_bind()
    event.listen(engine, 'before_cursor_execute', before_execute)
    try:
        yield statements
    finally:
        event.remove(engine, 'before_cursor_execute', before_execute)


@pytest.fixture
def stocked_catalog(db_session):
    category = Category(name='Performance clothes')
    color = Color(name='Crema', hex_code='#FAF7F2')
    size = Size(name='Mediano', code='M')
    branch = Branch(name='Central', city='La Paz', address='Centro')
    user = User(email='perf@example.com', full_name='Cliente', hashed_password='unused', role='CUSTOMER')
    db_session.add_all([category, color, size, branch, user])
    db_session.flush()
    for i in range(8):
        product = Product(name=f'Prenda {i}', price=29, category_id=category.id)
        db_session.add(product)
        db_session.flush()
        variant = ProductVariant(product_id=product.id, size_id=size.id, color_id=color.id, sku=f'PERF-{i}')
        db_session.add(variant)
        db_session.flush()
        db_session.add_all([
            Stock(variant_id=variant.id, branch_id=branch.id, quantity=5),
            CartItem(user_id=user.id, variant_id=variant.id, quantity=2),
        ])
    db_session.commit()
    user_id = user.id
    db_session.expunge_all()
    return user_id


def test_product_query_count_is_bounded(db_session, stocked_catalog):
    with count_selects(db_session) as queries:
        products = ProductService.list_products(db_session)
    assert len(products) == 8
    assert all(p.total_stock == 5 for p in products)
    assert len(queries) <= 3


def test_catalog_query_count_does_not_grow_with_page_size(db_session, stocked_catalog):
    counts = []
    for page_size in (1, 8):
        db_session.expunge_all()
        with count_selects(db_session) as queries:
            result = CatalogService.list_products(db_session, page_size=page_size)
        counts.append(len(queries))
        assert result.total == 8
        assert len(result.items) == page_size
        assert result.items[0].variants[0].branch_availability[0].quantity == 5
    assert counts[0] == counts[1]
    assert counts[1] <= 5


def test_cart_batches_stock_and_product_loading(db_session, stocked_catalog):
    with count_selects(db_session) as queries:
        cart = CartService.get_cart(db_session, stocked_catalog)
    assert len(cart.items) == 8
    assert cart.total_items == 16
    assert cart.total_amount == 464
    assert all(item.available_stock == 5 for item in cart.items)
    assert len(queries) <= 2


def test_public_registration_cannot_grant_admin(client):
    response = client.post('/api/v1/auth/register', json={
        'email': 'public@example.com', 'password': 'Password123!',
        'full_name': 'Public Customer', 'role': 'ADMIN',
    })
    assert response.status_code == 201
    assert response.json()['role'] == 'CUSTOMER'
    login = client.post('/api/v1/auth/login', json={
        'email': 'public@example.com', 'password': 'Password123!',
    })
    token = login.json()['access_token']
    assert client.get('/api/v1/users', headers={'Authorization': f'Bearer {token}'}).status_code == 403


@pytest.mark.asyncio
async def test_virtual_inference_runs_off_event_loop(monkeypatch):
    from app.api.v1 import virtual_fitting
    event_loop_thread = threading.get_ident()
    def inference(**kwargs):
        assert threading.get_ident() != event_loop_thread
        return b'result'
    monkeypatch.setattr(virtual_fitting, 'run_tryon_from_bytes', inference)
    monkeypatch.setattr(virtual_fitting.ActivityLogService, 'log_event', lambda **kwargs: None)
    result = await virtual_fitting.idm_virtual_tryon(
        person_image=UploadFile(io.BytesIO(b'person'), filename='person.jpg'),
        garment_image=UploadFile(io.BytesIO(b'garment'), filename='garment.jpg'),
        garment_description='Blusa', use_auto_mask=True, use_auto_crop=True,
        denoise_steps=30, seed=42, db=None, current_user=None,
    )
    assert result['result_image_b64'] == 'cmVzdWx0'
