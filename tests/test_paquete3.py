import pytest
from app.models.branch import Branch
from app.models.category import Category
from app.models.color import Color
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.size import Size
from app.models.stock import Stock
from app.models.user import User, UserRole
from app.core.security import get_password_hash, create_access_token


def _create_user(db_session, email, role, full_name, branch_id=None):
    user = User(
        email=email,
        hashed_password=get_password_hash("Password123!"),
        full_name=full_name,
        role=role,
        branch_id=branch_id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token = create_access_token(subject=user.id, claims={"role": user.role, "email": user.email})
    return user, token


def test_cu09_inventory_movements(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Setup
    branch = Branch(name="Sucursal Centro", city="La Paz", address="Calle Murillo 100")
    cat = Category(name="Camisas")
    sz = Size(name="Medium", code="M")
    col = Color(name="Azul", hex_code="#0000FF")
    db_session.add_all([branch, cat, sz, col])
    db_session.commit()

    prod = Product(name="Camisa Oxford", price=120.0, category_id=cat.id)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="CAM-OXF-M-AZU")
    db_session.add(variant)
    db_session.commit()

    # 1. Register ENTRY movement (+50 units)
    entry_payload = {
        "variant_id": variant.id,
        "branch_id": branch.id,
        "type": "ENTRY",
        "quantity": 50,
        "reason": "Ingreso por lote inicial del proveedor",
        "reference_number": "FAC-12345",
    }
    res = client.post("/api/v1/inventory/movements", json=entry_payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["previous_stock"] == 0
    assert data["new_stock"] == 50
    assert data["type"] == "ENTRY"
    assert data["sku"] == "CAM-OXF-M-AZU"

    # 2. Register EXIT movement (-10 units)
    exit_payload = {
        "variant_id": variant.id,
        "branch_id": branch.id,
        "type": "EXIT",
        "quantity": 10,
        "reason": "Venta directa en mostrador",
    }
    res2 = client.post("/api/v1/inventory/movements", json=exit_payload, headers=headers)
    assert res2.status_code == 201
    assert res2.json()["previous_stock"] == 50
    assert res2.json()["new_stock"] == 40

    # 3. Validation: insufficient stock on EXIT
    excess_exit = {
        "variant_id": variant.id,
        "branch_id": branch.id,
        "type": "EXIT",
        "quantity": 100,
        "reason": "Salida excesiva no permitida",
    }
    res_err = client.post("/api/v1/inventory/movements", json=excess_exit, headers=headers)
    assert res_err.status_code == 400
    assert "Stock insuficiente" in res_err.json()["detail"]

    # 4. List movements
    list_res = client.get("/api/v1/inventory/movements", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 2

    # 5. Branch inventory summary
    sum_res = client.get(f"/api/v1/inventory/summary/{branch.id}", headers=headers)
    assert sum_res.status_code == 200
    assert sum_res.json()["total_units"] == 40


def test_cu10_cross_branch_availability(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    b1 = Branch(name="Sucursal Centro", city="La Paz", address="Murillo 100")
    b2 = Branch(name="Sucursal Sur", city="La Paz", address="Calacoto 200")
    cat = Category(name="Pantalones")
    sz = Size(name="Large", code="L")
    col = Color(name="Negro", hex_code="#000000")
    db_session.add_all([b1, b2, cat, sz, col])
    db_session.commit()

    prod = Product(name="Pantalón Slim", price=180.0, category_id=cat.id)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="PAN-SLM-L-NEG")
    db_session.add(variant)
    db_session.commit()

    # Stock in b1 = 15, stock in b2 = 3 (low stock)
    s1 = Stock(variant_id=variant.id, branch_id=b1.id, quantity=15, min_alert_threshold=5)
    s2 = Stock(variant_id=variant.id, branch_id=b2.id, quantity=3, min_alert_threshold=5)
    db_session.add_all([s1, s2])
    db_session.commit()

    # Query variant availability
    res = client.get(f"/api/v1/stocks/variant/{variant.id}/availability", headers=headers)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    status_map = {item["branch_name"]: item["status"] for item in items}
    assert status_map["Sucursal Centro"] == "IN_STOCK"
    assert status_map["Sucursal Sur"] == "LOW_STOCK"

    # Query matrix
    matrix_res = client.get("/api/v1/stocks/matrix", headers=headers)
    assert matrix_res.status_code == 200
    matrix_data = matrix_res.json()
    assert len(matrix_data) == 1
    assert matrix_data[0]["total_quantity"] == 18


def test_cu11_catalog_filters_and_search(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    cat = Category(name="Camisas")
    sz = Size(name="Medium", code="M")
    col = Color(name="Blanco", hex_code="#FFFFFF")
    db_session.add_all([cat, sz, col])
    db_session.commit()

    p1 = Product(name="Camisa Formal Blanca", price=150.0, category_id=cat.id, gender="Hombre")
    p2 = Product(name="Blusa Seda", price=250.0, category_id=cat.id, gender="Mujer")
    db_session.add_all([p1, p2])
    db_session.commit()

    # 1. Get filters
    filters_res = client.get("/api/v1/catalog/filters", headers=headers)
    assert filters_res.status_code == 200
    assert len(filters_res.json()["categories"]) >= 1

    # 2. Search products
    search_res = client.get("/api/v1/catalog/products?search=Formal", headers=headers)
    assert search_res.status_code == 200
    assert search_res.json()["total"] == 1
    assert search_res.json()["items"][0]["name"] == "Camisa Formal Blanca"

    # 3. Filter by gender
    gender_res = client.get("/api/v1/catalog/products?gender=Mujer", headers=headers)
    assert gender_res.status_code == 200
    assert gender_res.json()["total"] == 1
    assert gender_res.json()["items"][0]["name"] == "Blusa Seda"


def test_cu12_shopping_cart(client, db_session):
    customer, token = _create_user(db_session, "cliente1@test.com", UserRole.CUSTOMER.value, "Cliente Uno")
    headers = {"Authorization": f"Bearer {token}"}

    cat = Category(name="Calzados")
    sz = Size(name="40", code="40")
    col = Color(name="Café", hex_code="#8B4513")
    db_session.add_all([cat, sz, col])
    db_session.commit()

    prod = Product(name="Zapatos de Cuero", price=320.0, category_id=cat.id)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="ZAP-CUE-40-CAF")
    db_session.add(variant)
    db_session.commit()

    # 1. Add item to cart
    add_res = client.post("/api/v1/cart/items", json={"variant_id": variant.id, "quantity": 2}, headers=headers)
    assert add_res.status_code == 200
    cart = add_res.json()
    assert cart["total_items"] == 2
    assert cart["total_amount"] == 640.0
    item_id = cart["items"][0]["id"]

    # 2. Update quantity
    upd_res = client.put(f"/api/v1/cart/items/{item_id}", json={"quantity": 3}, headers=headers)
    assert upd_res.status_code == 200
    assert upd_res.json()["total_items"] == 3
    assert upd_res.json()["total_amount"] == 960.0

    # 3. Remove item
    del_res = client.delete(f"/api/v1/cart/items/{item_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["total_items"] == 0


def test_cu13_reservations_flow(client, db_session):
    branch = Branch(name="Sucursal San Miguel", city="La Paz", address="Av. Montenegro #50")
    cat = Category(name="Abrigos")
    sz = Size(name="XL", code="XL")
    col = Color(name="Gris", hex_code="#808080")
    db_session.add_all([branch, cat, sz, col])
    db_session.commit()

    prod = Product(name="Chaqueta de Lana", price=450.0, category_id=cat.id)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="CHA-LAN-XL-GRI")
    db_session.add(variant)
    db_session.commit()

    # Stock available = 5 in branch
    stock = Stock(variant_id=variant.id, branch_id=branch.id, quantity=5)
    db_session.add(stock)
    db_session.commit()

    customer, cust_token = _create_user(db_session, "cliente2@test.com", UserRole.CUSTOMER.value, "Cliente Dos")
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    staff, staff_token = _create_user(db_session, "cajero@test.com", UserRole.CASHIER.value, "Cajero San Miguel", branch_id=branch.id)
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # 1. Customer creates reservation
    res_payload = {
        "branch_id": branch.id,
        "items": [{"variant_id": variant.id, "quantity": 1}],
        "customer_notes": "Pasaré mañana a las 16:00",
    }
    create_res = client.post("/api/v1/reservations", json=res_payload, headers=cust_headers)
    assert create_res.status_code == 201
    res_data = create_res.json()
    assert res_data["status"] == "PENDING"
    assert res_data["reservation_code"].startswith("RSV-")
    reservation_id = res_data["id"]

    # 2. Customer lists own reservations
    list_res = client.get("/api/v1/reservations", headers=cust_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # 3. Staff updates status to COMPLETED with note
    upd_res = client.patch(
        f"/api/v1/reservations/{reservation_id}/status",
        json={"status": "COMPLETED", "staff_notes": "Cliente probó la prenda y realizó la compra"},
        headers=staff_headers,
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["status"] == "COMPLETED"

    # 4. Check stats (Admin)
    admin, admin_token = _create_user(db_session, "admin_stats@test.com", UserRole.ADMIN.value, "Admin Stats")
    adm_headers = {"Authorization": f"Bearer {admin_token}"}
    stats_res = client.get("/api/v1/reservations/stats", headers=adm_headers)
    assert stats_res.status_code == 200
    assert stats_res.json()["completed"] == 1
