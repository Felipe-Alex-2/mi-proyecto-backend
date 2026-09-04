from app.models.branch import Branch
from app.models.category import Category
from app.models.color import Color
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.size import Size


def test_adjust_stock_and_query_inventory(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Setup Branch, Category, Size, Color, Product, Variant
    branch = Branch(name="Central", city="La Paz", address="Av. 16 de Julio #123")
    cat = Category(name="Vestidos")
    sz = Size(name="Small", code="S")
    col = Color(name="Rojo", hex_code="#FF0000")
    db_session.add_all([branch, cat, sz, col])
    db_session.commit()

    prod = Product(name="Vestido de Noche", price=350.0, category_id=cat.id)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="VES-ROJ-S")
    db_session.add(variant)
    db_session.commit()

    # Adjust stock to 25 units
    adjust_payload = {
        "variant_id": variant.id,
        "branch_id": branch.id,
        "quantity": 25,
    }
    res = client.post("/api/v1/stocks/adjust", json=adjust_payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["quantity"] == 25

    # Query branch inventory
    inv_res = client.get(f"/api/v1/stocks/branch/{branch.id}", headers=headers)
    assert inv_res.status_code == 200
    items = inv_res.json()
    assert len(items) == 1
    assert items[0]["product_name"] == "Vestido de Noche"
    assert items[0]["sku"] == "VES-ROJ-S"
    assert items[0]["quantity"] == 25
    assert items[0]["is_low_stock"] is False

    # Check product detail shows stock
    prod_res = client.get(f"/api/v1/products/{prod.id}", headers=headers)
    assert prod_res.status_code == 200
    assert prod_res.json()["total_stock"] == 25
