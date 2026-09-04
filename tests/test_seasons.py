from datetime import date, timedelta
from fastapi.testclient import TestClient


def test_create_and_manage_seasons(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    today = date.today()
    start_date = today.isoformat()
    end_date = (today + timedelta(days=90)).isoformat()

    # Create season
    res = client.post(
        "/api/v1/seasons",
        json={
            "name": "Primavera - Verano 2026",
            "description": "Colección de ropa ligera para clima cálido",
            "start_date": start_date,
            "end_date": end_date,
        },
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Primavera - Verano 2026"
    assert data["is_active"] is True
    assert data["is_expired"] is False
    season_id = data["id"]

    # Invalid dates (end before start)
    res_inv = client.post(
        "/api/v1/seasons",
        json={
            "name": "Temporada Invalida",
            "start_date": (today + timedelta(days=10)).isoformat(),
            "end_date": today.isoformat(),
        },
        headers=headers,
    )
    assert res_inv.status_code == 422

    # Duplicate name fails
    res_dup = client.post(
        "/api/v1/seasons",
        json={
            "name": "primavera - verano 2026",
            "start_date": start_date,
            "end_date": end_date,
        },
        headers=headers,
    )
    assert res_dup.status_code == 409

    # Toggle status
    res_toggle = client.patch(f"/api/v1/seasons/{season_id}/toggle-status", headers=headers)
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_active"] is False


def test_expired_season_flag(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    today = date.today()

    # Past season
    res = client.post(
        "/api/v1/seasons",
        json={
            "name": "Invierno 2024",
            "start_date": (today - timedelta(days=120)).isoformat(),
            "end_date": (today - timedelta(days=30)).isoformat(),
        },
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["is_expired"] is True
