import pytest


@pytest.mark.parametrize('endpoint,required,optional', [
    ('branches', {'name':'Sucursal Opcional','city':'La Paz','address':'Av. Principal 100'}, {'phone':'', 'opening_hours':'   '}),
    ('attributes/categories', {'name':'Categoría opcional'}, {'description':'   '}),
    ('attributes/sizes', {'name':'Mediana','code':'M'}, {'category_type':''}),
    ('seasons', {'name':'Verano opcional','start_date':'2027-01-01','end_date':'2027-02-01'}, {'description':''}),
    ('promotions', {'name':'Oferta opcional','start_date':'2027-01-01','end_date':'2027-02-01','discount_percent':10}, {'description':'   '}),
    ('suppliers', {'company_name':'Proveedor Opcional','contact_name':'Persona Contacto','email':'ventas@example.com','phone':'70012345'}, {'tax_id':'', 'address':'   '}),
])
def test_optional_fields_can_be_blank_on_create_and_cleared_on_edit(client, admin_token, endpoint, required, optional):
    headers = {'Authorization': f'Bearer {admin_token}'}
    url = f'/api/v1/{endpoint}'
    created = client.post(url, headers=headers, json={**required, **optional})
    assert created.status_code == 201, created.text
    for field in optional:
        assert created.json()[field] in (None, 'GENERAL')
    item_url = f"{url}/{created.json()['id']}"
    values = {field: 'Dato opcional' for field in optional}
    updated = client.put(item_url, headers=headers, json=values)
    assert updated.status_code == 200, updated.text
    # An unrelated edit must retain optional data.
    preserved = client.put(item_url, headers=headers, json={})
    assert preserved.status_code == 200
    for field in optional:
        assert preserved.json()[field] == 'Dato opcional'
    cleared = client.put(item_url, headers=headers, json=optional)
    assert cleared.status_code == 200, cleared.text
    for field in optional:
        assert cleared.json()[field] in (None, 'GENERAL')


def test_product_optional_description_image_and_auto_sku(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    cat = client.post('/api/v1/attributes/categories', headers=headers, json={'name':'Ropa'}).json()
    size = client.post('/api/v1/attributes/sizes', headers=headers, json={'name':'Mediana','code':'M'}).json()
    color = client.post('/api/v1/attributes/colors', headers=headers, json={'name':'Azul','hex_code':'#123456'}).json()
    result = client.post('/api/v1/products', headers=headers, json={
        'name':'Polera opcional', 'price':50, 'category_id':cat['id'], 'description':'', 'image_url':'  ',
        'season_id':'', 'supplier_id':'  ', 'promotion_id':'',
        'variants':[{'size_id':size['id'], 'color_id':color['id'], 'sku':''}],
    })
    assert result.status_code == 201, result.text
    assert result.json()['description'] is None
    assert result.json()['image_url'] is None
    assert result.json()['season_id'] is None
    assert result.json()['supplier_id'] is None
    assert result.json()['promotion_id'] is None
    assert result.json()['variants'][0]['sku']
    url = f"/api/v1/products/{result.json()['id']}"
    assert client.put(url, headers=headers, json={'description':'Descripción anterior'}).status_code == 200
    assert client.put(url, headers=headers, json={'description':'   '}).json()['description'] is None
    # Partial updates of required attributes still reject empty values.
    for field in ('name','category_id','gender'):
        assert client.put(url, headers=headers, json={field:'   '}).status_code == 422


def test_optional_phone_clears_and_empty_password_preserves_credentials(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    url = '/api/v1/users/me'
    assert client.put(url, headers=headers, json={'phone':'70012345'}).status_code == 200
    changed = client.put(url, headers=headers, json={'phone':'  ', 'password':''})
    assert changed.status_code == 200, changed.text
    assert changed.json()['phone'] is None
    login = client.post('/api/v1/auth/login', json={'email':'admin_fixture@example.com','password':'Password123!'})
    assert login.status_code == 200


def test_optional_payment_email_can_be_blank_but_supplied_values_are_validated(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    branch = client.post('/api/v1/branches', headers=headers, json={'name':'Caja opcional','city':'La Paz','address':'Calle 100','phone':''}).json()
    data = {'branch_id':branch['id'], 'customer_name':'Cliente', 'concept':'Venta de prueba', 'amount':10,
            'customer_email':'  ', 'notes':'', 'reservation_id':''}
    response = client.post('/api/v1/payments', headers=headers, json=data)
    assert response.status_code == 201, response.text
    assert response.json()['customer_email'] is None
    assert response.json()['notes'] is None
    for invalid in ('correo-invalido', {'incorrect':'type'}):
        assert client.post('/api/v1/payments', headers=headers, json={**data, 'customer_email':invalid}).status_code == 422
    assert client.post('/api/v1/payments', headers=headers, json={**data, 'customer_name':'  '}).status_code == 422
