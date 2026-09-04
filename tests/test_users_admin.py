import pytest
from app.models.user import User, UserRole
from app.core.security import get_password_hash, create_access_token


def create_test_user(db_session, email: str, role: str = "ADMIN", is_active: bool = True) -> User:
    user = User(
        email=email,
        hashed_password=get_password_hash("Password123!"),
        full_name=f"User {email}",
        role=role,
        is_active=is_active,
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


def test_admin_list_users(client, db_session):
    admin = create_test_user(db_session, "admin_list@example.com", role="ADMIN")
    create_test_user(db_session, "cashier1@example.com", role="CASHIER")
    create_test_user(db_session, "manager1@example.com", role="STORE_MANAGER")

    headers = get_auth_header(admin)
    response = client.get("/api/v1/users", headers=headers)
    assert response.status_code == 200
    users = response.json()
    assert len(users) >= 3

    # Test filtering by role
    res_cashier = client.get("/api/v1/users?role=CASHIER", headers=headers)
    assert res_cashier.status_code == 200
    cashiers = res_cashier.json()
    assert len(cashiers) == 1
    assert cashiers[0]["role"] == "CASHIER"


def test_admin_create_employee(client, db_session):
    admin = create_test_user(db_session, "admin_create@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    payload = {
        "email": "new_cashier@fashionstore.com",
        "full_name": "Carlos Cajero",
        "password": "SecurePassword123!",
        "role": "CASHIER",
        "phone": "+591 70012345",
    }
    response = client.post("/api/v1/users", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new_cashier@fashionstore.com"
    assert data["full_name"] == "Carlos Cajero"
    assert data["role"] == "CASHIER"
    assert data["phone"] == "+591 70012345"
    assert data["is_active"] is True


def test_admin_update_user(client, db_session):
    admin = create_test_user(db_session, "admin_update@example.com", role="ADMIN")
    emp = create_test_user(db_session, "emp_to_update@example.com", role="CASHIER")
    headers = get_auth_header(admin)

    update_payload = {
        "full_name": "Carlos Promovido",
        "role": "STORE_MANAGER",
        "phone": "+591 78999999",
    }
    response = client.put(f"/api/v1/users/{emp.id}", json=update_payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Carlos Promovido"
    assert data["role"] == "STORE_MANAGER"
    assert data["phone"] == "+591 78999999"


def test_admin_toggle_user_status(client, db_session):
    admin = create_test_user(db_session, "admin_toggle@example.com", role="ADMIN")
    emp = create_test_user(db_session, "emp_toggle@example.com", role="CASHIER", is_active=True)
    headers = get_auth_header(admin)

    # 1. Deactivate employee
    res_deactivate = client.patch(f"/api/v1/users/{emp.id}/toggle-status", headers=headers)
    assert res_deactivate.status_code == 200
    assert res_deactivate.json()["is_active"] is False

    # 2. Deactivated employee cannot log in
    res_login = client.post(
        "/api/v1/auth/login",
        json={"email": "emp_toggle@example.com", "password": "Password123!"},
    )
    assert res_login.status_code == 401
    assert "inactive" in res_login.json()["detail"].lower()

    # 3. Reactivate employee
    res_reactivate = client.patch(f"/api/v1/users/{emp.id}/toggle-status", headers=headers)
    assert res_reactivate.status_code == 200
    assert res_reactivate.json()["is_active"] is True


def test_admin_cannot_self_deactivate(client, db_session):
    admin = create_test_user(db_session, "admin_self@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    response = client.patch(f"/api/v1/users/{admin.id}/toggle-status", headers=headers)
    assert response.status_code == 400
    assert "No puedes desactivar tu propia cuenta" in response.json()["detail"]


def test_non_admin_forbidden(client, db_session):
    cashier = create_test_user(db_session, "regular_cashier@example.com", role="CASHIER")
    headers = get_auth_header(cashier)

    # Trying to list users
    res_list = client.get("/api/v1/users", headers=headers)
    assert res_list.status_code == 403
    assert "permisos de Administrador" in res_list.json()["detail"]

    # Trying to create user
    res_create = client.post(
        "/api/v1/users",
        json={
            "email": "unauthorized@example.com",
            "full_name": "Test",
            "password": "Password123!",
            "role": "CASHIER",
        },
        headers=headers,
    )
    assert res_create.status_code == 403
