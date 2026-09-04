from app.models.category import Category
from app.models.color import Color
from app.models.size import Size


def test_create_and_list_products_with_variants(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create Category, Size, Color
    cat = Category(name="Poleras", description="Poleras de algodon")
    sz = Size(name="Mediano", code="M")
    col = Color(name="Azul Marino", hex_code="#001F3F")
    db_session.add_all([cat, sz, col])
    db_session.commit()

    # 2. Create Product with variant
    create_payload = {
        "name": "Polera Estampada Urban",
        "description": "Edicion limitada 100% algodon",
        "price": 129.50,
        "category_id": cat.id,
        "gender": "UNISEX",
        "variants": [
            {
                "size_id": sz.id,
                "color_id": col.id,
                "sku": "POL-AZU-M",
                "price_override": None,
            }
        ],
    }

    res = client.post("/api/v1/products", json=create_payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Polera Estampada Urban"
    assert data["price"] == 129.50
    assert data["category_name"] == "Poleras"
    assert len(data["variants"]) == 1
    assert data["variants"][0]["sku"] == "POL-AZU-M"
    assert data["variants"][0]["size_code"] == "M"
    assert data["variants"][0]["color_name"] == "Azul Marino"

    # 3. List products
    res_list = client.get("/api/v1/products", headers=headers)
    assert res_list.status_code == 200
    products = res_list.json()
    assert len(products) == 1
    assert products[0]["id"] == data["id"]

    # 4. Toggle status
    res_toggle = client.patch(f"/api/v1/products/{data['id']}/toggle-status", headers=headers)
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_active"] is False


def test_duplicate_sku_rejected(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    cat = Category(name="Jeans")
    sz1 = Size(name="Talla 30", code="30")
    sz2 = Size(name="Talla 32", code="32")
    col = Color(name="Negro", hex_code="#000000")
    db_session.add_all([cat, sz1, sz2, col])
    db_session.commit()

    # Create first product
    payload1 = {
        "name": "Jean Slim Fit",
        "price": 250.0,
        "category_id": cat.id,
        "variants": [{"size_id": sz1.id, "color_id": col.id, "sku": "JEA-NEG-30"}],
    }
    res1 = client.post("/api/v1/products", json=payload1, headers=headers)
    assert res1.status_code == 201

    # Attempt second product with duplicate SKU
    payload2 = {
        "name": "Jean Relaxed",
        "price": 260.0,
        "category_id": cat.id,
        "variants": [{"size_id": sz2.id, "color_id": col.id, "sku": "JEA-NEG-30"}],
    }
    res2 = client.post("/api/v1/products", json=payload2, headers=headers)
    assert res2.status_code == 400
    assert "ya está en uso" in res2.json()["detail"]
