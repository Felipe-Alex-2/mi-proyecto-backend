from fastapi.testclient import TestClient
from app.models.user import UserRole


def test_create_and_list_categories(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Create category
    res = client.post(
        "/api/v1/attributes/categories",
        json={"name": "Camisas", "description": "Camisas formales y casuales"},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Camisas"
    assert data["is_active"] is True
    cat_id = data["id"]

    # Duplicate name fails
    res_dup = client.post(
        "/api/v1/attributes/categories",
        json={"name": "camisas"},
        headers=headers,
    )
    assert res_dup.status_code == 409

    # List categories
    res_list = client.get("/api/v1/attributes/categories", headers=headers)
    assert res_list.status_code == 200
    names = [c["name"] for c in res_list.json()]
    assert "Camisas" in names

    # Toggle status
    res_toggle = client.patch(f"/api/v1/attributes/categories/{cat_id}/toggle-status", headers=headers)
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_active"] is False


def test_create_and_list_sizes(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create size
    res = client.post(
        "/api/v1/attributes/sizes",
        json={"name": "Medium", "code": "M", "category_type": "GENERAL"},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["code"] == "M"

    # Duplicate code fails
    res_dup = client.post(
        "/api/v1/attributes/sizes",
        json={"name": "Mediana", "code": "m"},
        headers=headers,
    )
    assert res_dup.status_code == 409

    # List sizes
    res_list = client.get("/api/v1/attributes/sizes", headers=headers)
    assert res_list.status_code == 200
    codes = [s["code"] for s in res_list.json()]
    assert "M" in codes


def test_create_and_list_colors(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create color
    res = client.post(
        "/api/v1/attributes/colors",
        json={"name": "Azul Marino", "hex_code": "#001F3F"},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Azul Marino"
    assert data["hex_code"] == "#001F3F"

    # Invalid hex format fails
    res_inv = client.post(
        "/api/v1/attributes/colors",
        json={"name": "Verde Invalido", "hex_code": "123456"},
        headers=headers,
    )
    assert res_inv.status_code == 422

    # Duplicate name fails
    res_dup = client.post(
        "/api/v1/attributes/colors",
        json={"name": "azul marino", "hex_code": "#002244"},
        headers=headers,
    )
    assert res_dup.status_code == 409
