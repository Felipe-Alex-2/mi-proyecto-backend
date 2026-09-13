import pytest
from app.models.user import User
from app.models.category import Category
from app.models.size import Size
from app.models.color import Color
from app.models.product import Product
from app.core.security import get_password_hash, create_access_token


def create_admin_user(db_session, email="val_admin@example.com"):
    user = User(
        email=email,
        hashed_password=get_password_hash("Password123!"),
        full_name="Admin Validator",
        role="ADMIN",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def get_auth_header(user: User) -> dict:
    token = create_access_token(
        subject=user.id,
        claims={"role": user.role, "email": user.email},
    )
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------
# 1. PRUEBAS DE VALIDACIÓN DE CONTRASEÑAS FUERTES
# ----------------------------------------------------
def test_password_validation_rules(client, db_session):
    base_payload = {
        "email": "pwd_val@example.com",
        "full_name": "Validador Contraseña",
    }

    # Menos de 8 caracteres
    res = client.post("/api/v1/auth/register", json={**base_payload, "password": "Ab1!"})
    assert res.status_code == 422

    # Sin mayúscula
    res = client.post("/api/v1/auth/register", json={**base_payload, "password": "password123!"})
    assert res.status_code == 422

    # Sin minúscula
    res = client.post("/api/v1/auth/register", json={**base_payload, "password": "PASSWORD123!"})
    assert res.status_code == 422

    # Sin número
    res = client.post("/api/v1/auth/register", json={**base_payload, "password": "Password!!!!"})
    assert res.status_code == 422

    # Sin símbolo
    res = client.post("/api/v1/auth/register", json={**base_payload, "password": "Password123"})
    assert res.status_code == 422

    # Contraseña válida
    res = client.post("/api/v1/auth/register", json={**base_payload, "password": "ValidPassword123!"})
    assert res.status_code == 201


# ----------------------------------------------------
# 2. PRUEBAS DE CAMPOS VACÍOS O CON ESPACIOS EN BLANCO
# ----------------------------------------------------
def test_reject_whitespace_in_branch_create_and_update(client, db_session):
    admin = create_admin_user(db_session, "admin_white_br@example.com")
    headers = get_auth_header(admin)

    # Nombre con solo espacios en create
    res_create = client.post(
        "/api/v1/branches",
        json={"name": "   ", "city": "La Paz", "address": "Av. Principal #100"},
        headers=headers,
    )
    assert res_create.status_code == 422

    # Ciudad con solo espacios
    res_city = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Válida", "city": "   ", "address": "Av. Principal #100"},
        headers=headers,
    )
    assert res_city.status_code == 422

    # Crear una válida
    res_ok = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Para Editar", "city": "La Paz", "address": "Av. Principal #100"},
        headers=headers,
    )
    assert res_ok.status_code == 201
    branch_id = res_ok.json()["id"]

    # Editar con nombre vacío o solo espacios
    res_edit = client.put(
        f"/api/v1/branches/{branch_id}",
        json={"name": "   "},
        headers=headers,
    )
    assert res_edit.status_code == 422


def test_reject_whitespace_in_product_create_and_update(client, db_session):
    admin = create_admin_user(db_session, "admin_white_prod@example.com")
    headers = get_auth_header(admin)

    cat = Category(name="Categoría Test Whitespace")
    db_session.add(cat)
    db_session.commit()

    # Create con nombre de solo espacios
    res = client.post(
        "/api/v1/products",
        json={"name": "    ", "price": 100.0, "category_id": cat.id},
        headers=headers,
    )
    assert res_status_code == 422 if (res_status_code := res.status_code) else 422

    # Create válido
    res_ok = client.post(
        "/api/v1/products",
        json={"name": "Prenda Válida Para Edit", "price": 100.0, "category_id": cat.id},
        headers=headers,
    )
    assert res_ok.status_code == 201
    prod_id = res_ok.json()["id"]

    # Edit con espacios
    res_edit = client.put(
        f"/api/v1/products/{prod_id}",
        json={"name": "  "},
        headers=headers,
    )
    assert res_edit.status_code == 422


# ----------------------------------------------------
# 3. PRUEBAS DE DUPLICADOS (UNICIDAD)
# ----------------------------------------------------
def test_duplicate_product_name_rejected(client, db_session):
    admin = create_admin_user(db_session, "admin_dup_prod@example.com")
    headers = get_auth_header(admin)

    cat = Category(name="Categoría Dup Test")
    db_session.add(cat)
    db_session.commit()

    payload1 = {"name": "Camisa Denim Vintage", "price": 150.0, "category_id": cat.id}
    res1 = client.post("/api/v1/products", json=payload1, headers=headers)
    assert res1.status_code == 201

    # Crear con mismo nombre (incluso con espacios y mayúsculas/minúsculas diferentes)
    payload2 = {"name": "  camisa denim vintage  ", "price": 180.0, "category_id": cat.id}
    res2 = client.post("/api/v1/products", json=payload2, headers=headers)
    assert res2.status_code == 409
    assert "Ya existe una prenda" in res2.json()["detail"]


def test_duplicate_user_email_on_profile_update(client, db_session):
    # Crear usuario 1
    user1 = User(
        email="user1_dup@example.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="User Uno",
        role="ADMIN",
        is_active=True,
    )
    # Crear usuario 2
    user2 = User(
        email="user2_dup@example.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="User Dos",
        role="ADMIN",
        is_active=True,
    )
    db_session.add_all([user1, user2])
    db_session.commit()

    # Iniciar sesión como usuario 2 e intentar cambiarse el email al de usuario 1
    headers = get_auth_header(user2)
    res = client.put(
        "/api/v1/users/me",
        headers=headers,
        json={"email": "user1_dup@example.com"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"].lower()
    assert "taken" in detail or "registrado" in detail
