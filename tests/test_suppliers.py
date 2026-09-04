from fastapi.testclient import TestClient


def test_create_and_manage_suppliers(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create supplier
    res = client.post(
        "/api/v1/suppliers",
        json={
            "company_name": "Textiles Andinos S.A.",
            "contact_name": "Roberto Gómez",
            "tax_id": "1029384756",
            "email": "contacto@textilesandinos.com",
            "phone": "+591 2 2789101",
            "address": "Parque Industrial Manzana 4, Lote 12",
        },
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["company_name"] == "Textiles Andinos S.A."
    assert data["is_active"] is True
    supplier_id = data["id"]

    # Duplicate company name fails
    res_dup = client.post(
        "/api/v1/suppliers",
        json={
            "company_name": "textiles andinos s.a.",
            "contact_name": "Otro Contacto",
            "email": "otro@textilesandinos.com",
            "phone": "+591 2 2789102",
        },
        headers=headers,
    )
    assert res_dup.status_code == 409

    # Search suppliers
    res_search = client.get("/api/v1/suppliers?search=Andinos", headers=headers)
    assert res_search.status_code == 200
    assert len(res_search.json()) >= 1

    # Update supplier
    res_upd = client.put(
        f"/api/v1/suppliers/{supplier_id}",
        json={"contact_name": "Roberto Gómez V."},
        headers=headers,
    )
    assert res_upd.status_code == 200
    assert res_upd.json()["contact_name"] == "Roberto Gómez V."

    # Toggle status
    res_toggle = client.patch(f"/api/v1/suppliers/{supplier_id}/toggle-status", headers=headers)
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_active"] is False
