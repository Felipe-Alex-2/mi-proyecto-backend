import pytest
from unittest.mock import patch
from app.modelos.sucursal import Sucursal
from app.modelos.categoria import Categoria
from app.modelos.color import Color
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.talla import Talla
from app.modelos.stock import Stock
from app.modelos.movimiento_inventario import MovimientoInventario, TipoMovimiento
from app.modelos.usuario import Usuario, RolUsuario
from app.nucleo.seguridad import get_password_hash, create_access_token


def _create_user(db_session, email, role, full_name, branch_id=None):
    user = Usuario(
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


def _setup_test_catalog(db_session):
    branch = Sucursal(name="Sucursal PayPal Test", city="Santa Cruz", address="Av. San Martin")
    cat = Categoria(name="Vestidos")
    sz = Talla(name="Large", code="L")
    col = Color(name="Rojo", hex_code="#FF0000")
    db_session.add_all([branch, cat, sz, col])
    db_session.commit()

    prod = Producto(name="Vestido de Verano", price=150.0, category_id=cat.id)
    db_session.add(prod)
    db_session.commit()

    variant = VarianteProducto(
        product_id=prod.id,
        size_id=sz.id,
        color_id=col.id,
        sku="TEST-SKU-PP-001",
    )
    db_session.add(variant)
    db_session.commit()

    stock = Stock(variant_id=variant.id, branch_id=branch.id, quantity=15, min_alert_threshold=2)
    db_session.add(stock)
    db_session.commit()

    return branch, variant


def test_reservation_payment_fields_default_and_complete(client, admin_token, db_session):
    customer, customer_token = _create_user(db_session, "paypal_cust1@test.com", RolUsuario.CUSTOMER.value, "Cliente Uno")
    branch, variant = _setup_test_catalog(db_session)

    # 1. Create reservation with EFECTIVO
    res = client.post(
        "/api/v1/reservations",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "branch_id": branch.id,
            "items": [{"variant_id": variant.id, "quantity": 2}],
            "customer_notes": "Pago en efectivo en tienda",
            "payment_method": "EFECTIVO",
        },
    )
    assert res.status_code == 201
    data = res.json()
    res_id = data["id"]
    assert data["payment_method"] == "EFECTIVO"
    assert data["payment_status"] == "PENDING"
    assert data["total_amount"] == 300.0

    # 2. Staff completes reservation in store and marks it as PAID with EFECTIVO
    update_res = client.patch(
        f"/api/v1/reservations/{res_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "status": "COMPLETED",
            "staff_notes": "Cliente pagó en efectivo en caja y retiró prendas",
            "payment_method": "EFECTIVO",
            "payment_status": "PAID",
        },
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["status"] == "COMPLETED"
    assert updated_data["payment_status"] == "PAID"
    assert updated_data["payment_method"] == "EFECTIVO"

    # Verify inventory movement was created and has payment fields
    mov = db_session.query(MovimientoInventario).filter(
        MovimientoInventario.reference_number == updated_data["reservation_code"],
        MovimientoInventario.type == TipoMovimiento.EXIT.value,
    ).first()
    assert mov is not None
    assert mov.payment_method == "EFECTIVO"
    assert mov.payment_status == "PAID"
    assert float(mov.amount) == 300.0


def test_paypal_order_create_and_capture(client, db_session):
    customer, customer_token = _create_user(db_session, "paypal_cust2@test.com", RolUsuario.CUSTOMER.value, "Cliente Dos")
    branch, variant = _setup_test_catalog(db_session)

    with patch("app.servicios.paypal_service.PayPalService.create_order") as mock_create, \
         patch("app.servicios.paypal_service.PayPalService.capture_order") as mock_capture:
        
        mock_create.return_value = {
            "order_id": "TEST-PP-ORDER-123",
            "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=TEST-PP-ORDER-123&fundingSource=paypal",
        }
        mock_capture.return_value = {
            "order_id": "TEST-PP-ORDER-123",
            "capture_id": "CAPTURE-999-XYZ",
            "status": "COMPLETED",
        }

        # 1. Call paypal-order endpoint
        resp = client.post(
            "/api/v1/reservations/paypal-order",
            headers={"Authorization": f"Bearer {customer_token}"},
            json={
                "branch_id": branch.id,
                "items": [{"variant_id": variant.id, "quantity": 1}],
                "customer_notes": "Pago con PayPal Sandbox",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["order_id"] == "TEST-PP-ORDER-123"
        assert "sandbox.paypal.com" in data["approval_url"]
        assert data["reservation"]["payment_method"] == "PAYPAL"
        assert data["reservation"]["payment_status"] == "PENDING"
        assert data["reservation"]["total_amount"] == 150.0

        # 2. Call paypal-capture endpoint
        cap_resp = client.post(
            "/api/v1/reservations/paypal-capture",
            headers={"Authorization": f"Bearer {customer_token}"},
            json={"paypal_order_id": "TEST-PP-ORDER-123"},
        )
        assert cap_resp.status_code == 200
        cap_data = cap_resp.json()
        assert cap_data["status"] == "COMPLETED"
        assert cap_data["capture_id"] == "CAPTURE-999-XYZ"
        assert cap_data["reservation"]["payment_status"] == "PAID"
        assert cap_data["reservation"]["status"] == "CONFIRMED"
