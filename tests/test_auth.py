import pytest


def test_register_user_success(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert "id" in data
    assert "hashed_password" not in data


def test_register_duplicate_email(client):
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "Test User",
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    assert "already registered" in res2.json()["detail"]


def test_register_short_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "shortpwd@example.com",
            "password": "short",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 422


def test_login_success(client):
    # Register user first
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "Password123!",
            "full_name": "Login User",
        },
    )

    # Login
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "login@example.com"


def test_login_invalid_password(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "wrongpwd@example.com",
            "password": "Password123!",
            "full_name": "Login User",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrongpwd@example.com",
            "password": "WrongPassword!",
        },
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_refresh_token(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "refresh@example.com",
            "password": "Password123!",
            "full_name": "Refresh User",
        },
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={
            "email": "refresh@example.com",
            "password": "Password123!",
        },
    )
    refresh_token = login_res.json()["refresh_token"]

    refresh_res = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res.status_code == 200
    assert "access_token" in refresh_res.json()


def test_logout_and_blacklist(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout@example.com",
            "password": "Password123!",
            "full_name": "Logout User",
        },
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={
            "email": "logout@example.com",
            "password": "Password123!",
        },
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify /me works before logout
    me_res = client.get("/api/v1/users/me", headers=headers)
    assert me_res.status_code == 200

    # Logout
    logout_res = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 200
    assert "Successfully logged out" in logout_res.json()["message"]

    # Verify /me is rejected after logout
    me_after_logout = client.get("/api/v1/users/me", headers=headers)
    assert me_after_logout.status_code == 401
    assert "revoked" in me_after_logout.json()["detail"]
