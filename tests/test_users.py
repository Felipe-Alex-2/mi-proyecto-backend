import pytest


def test_get_me_unauthorized(client):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_get_and_update_me(client):
    # Register & Login
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "updateuser@example.com",
            "password": "Password123!",
            "full_name": "Original Name",
        },
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={
            "email": "updateuser@example.com",
            "password": "Password123!",
        },
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get /me
    me_res = client.get("/api/v1/users/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["full_name"] == "Original Name"

    # Update full_name
    update_res = client.put(
        "/api/v1/users/me",
        headers=headers,
        json={"full_name": "Updated Name"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["full_name"] == "Updated Name"

    # Verify updated profile
    me_res2 = client.get("/api/v1/users/me", headers=headers)
    assert me_res2.json()["full_name"] == "Updated Name"
