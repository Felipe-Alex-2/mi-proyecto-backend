import pytest
from app.models.user import User
from app.models.branch import Branch
from app.core.security import get_password_hash, create_access_token


def create_test_user(db_session, email: str, role: str = "ADMIN") -> User:
    user = User(
        email=email,
        hashed_password=get_password_hash("Password123!"),
        full_name=f"User {email}",
        role=role,
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


def test_create_branch_success(client, db_session):
    admin = create_test_user(db_session, "admin_branch@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    payload = {
        "name": "Sucursal Calacoto",
        "city": "La Paz",
        "address": "Av. Ballivián #1234, Calacoto",
        "phone": "+591 2 2791234",
        "opening_hours": "Lun - Sáb: 09:00 - 21:00",
    }
    response = client.post("/api/v1/branches", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Sucursal Calacoto"
    assert data["city"] == "La Paz"
    assert data["is_active"] is True
    assert data["staff_count"] == 0


def test_duplicate_branch_in_same_city_fails(client, db_session):
    admin = create_test_user(db_session, "admin_dup@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    payload = {
        "name": "Sucursal Central",
        "city": "Cochabamba",
        "address": "Calle España #500",
    }
    # 1. Create first
    res1 = client.post("/api/v1/branches", json=payload, headers=headers)
    assert res1.status_code == 201

    # 2. Duplicate in same city should fail (FA03)
    res2 = client.post("/api/v1/branches", json=payload, headers=headers)
    assert res2.status_code == 409
    assert "Ya existe una sucursal" in res2.json()["detail"]


def test_same_branch_name_in_different_city_allowed(client, db_session):
    admin = create_test_user(db_session, "admin_diff@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    # Same name in Santa Cruz
    res1 = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Centro", "city": "Santa Cruz", "address": "Av. Monseñor #10"},
        headers=headers,
    )
    assert res1.status_code == 201

    # Same name in La Paz is allowed
    res2 = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Centro", "city": "La Paz", "address": "Av. Mariscal Santa Cruz #50"},
        headers=headers,
    )
    assert res2.status_code == 201


def test_list_branches_filter_by_city(client, db_session):
    admin = create_test_user(db_session, "admin_list_br@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    client.post(
        "/api/v1/branches",
        json={"name": "Branch LP 1", "city": "La Paz", "address": "Dirección 1"},
        headers=headers,
    )
    client.post(
        "/api/v1/branches",
        json={"name": "Branch SCZ 1", "city": "Santa Cruz", "address": "Dirección 2"},
        headers=headers,
    )

    # Filter by La Paz
    res_lp = client.get("/api/v1/branches?city=La Paz", headers=headers)
    assert res_lp.status_code == 200
    items = res_lp.json()
    assert len(items) == 1
    assert items[0]["city"] == "La Paz"


def test_assign_staff_and_transfer(client, db_session):
    admin = create_test_user(db_session, "admin_staff@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    # Create 2 branches
    res_b1 = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Norte", "city": "La Paz", "address": "Calle 1"},
        headers=headers,
    )
    b1_id = res_b1.json()["id"]

    res_b2 = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Sur", "city": "La Paz", "address": "Calle 2"},
        headers=headers,
    )
    b2_id = res_b2.json()["id"]

    # Create Store Manager & Cashier
    manager = create_test_user(db_session, "manager_store@example.com", role="STORE_MANAGER")
    cashier = create_test_user(db_session, "cashier_store@example.com", role="CASHIER")

    # 1. Assign both to Branch 1
    assign_res = client.post(
        f"/api/v1/branches/{b1_id}/staff",
        json={"user_ids": [manager.id, cashier.id]},
        headers=headers,
    )
    assert assign_res.status_code == 200
    data1 = assign_res.json()
    assert data1["staff_count"] == 2
    assert data1["manager"]["id"] == manager.id
    assert len(data1["cashiers"]) == 1

    # 2. Transfer cashier from Branch 1 to Branch 2 (FA01)
    transfer_res = client.post(
        f"/api/v1/branches/{b2_id}/staff",
        json={"user_ids": [cashier.id]},
        headers=headers,
    )
    assert transfer_res.status_code == 200
    data2 = transfer_res.json()
    assert data2["staff_count"] == 1
    assert data2["cashiers"][0]["id"] == cashier.id

    # Verify Branch 1 now only has 1 employee (manager)
    b1_check = client.get(f"/api/v1/branches/{b1_id}", headers=headers)
    assert b1_check.json()["staff_count"] == 1
    assert len(b1_check.json()["cashiers"]) == 0


def test_toggle_branch_status(client, db_session):
    admin = create_test_user(db_session, "admin_toggle_br@example.com", role="ADMIN")
    headers = get_auth_header(admin)

    res = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Cierre", "city": "Oruro", "address": "Plaza Principal"},
        headers=headers,
    )
    b_id = res.json()["id"]
    assert res.json()["is_active"] is True

    # Deactivate (cierre temporal - FA02)
    res_deact = client.patch(f"/api/v1/branches/{b_id}/toggle-status", headers=headers)
    assert res_deact.status_code == 200
    assert res_deact.json()["is_active"] is False

    # Reactivate
    res_react = client.patch(f"/api/v1/branches/{b_id}/toggle-status", headers=headers)
    assert res_react.status_code == 200
    assert res_react.json()["is_active"] is True


def test_non_admin_cannot_create_branch(client, db_session):
    cashier = create_test_user(db_session, "cashier_unauth@example.com", role="CASHIER")
    headers = get_auth_header(cashier)

    res = client.post(
        "/api/v1/branches",
        json={"name": "Sucursal Ilegal", "city": "Tarija", "address": "Calle Falsa"},
        headers=headers,
    )
    assert res.status_code == 403
