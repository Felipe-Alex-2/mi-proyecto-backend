import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from app.models.branch import Branch
from app.models.category import Category
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.size import Size
from app.models.color import Color
from app.models.stock import Stock
from app.models.reservation import Reservation
from app.models.reservation_item import ReservationItem
from app.models.inventory_movement import InventoryMovement, MovementType
from app.models.user import User, UserRole
from app.core.security import get_password_hash


def _setup_catalog(db_session):
    branch = Branch(name="Sucursal POS Central", city="La Paz", address="Av. Comercio 123", is_active=True)
    cat = Category(name="Ropa POS")
    sz = Size(name="M POS", code="M-POS")
    col = Color(name="Negro POS", hex_code="#000000")
    customer = User(
        email="cliente_pos@test.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="Cliente POS",
        role=UserRole.CUSTOMER.value,
        is_active=True,
    )
    db_session.add_all([branch, cat, sz, col, customer])
    db_session.commit()

    prod = Product(name="Camisa POS Elegante", price=25.0, category_id=cat.id, is_active=True)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="SKU-POS-001")
    db_session.add(variant)
    db_session.commit()

    stock = Stock(variant_id=variant.id, branch_id=branch.id, quantity=20)
    db_session.add(stock)
    db_session.commit()

    return branch, customer, variant


def test_pos_cash_payment_flow(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    branch, customer, variant = _setup_catalog(db_session)
    now = datetime.now(timezone.utc)

    # 1. Create a reservation that is pending payment in store
    reservation = Reservation(
        reservation_code="RSV-TEST-POS",
        customer_id=customer.id,
        branch_id=branch.id,
        status="CONFIRMED",
        payment_method="EFECTIVO",
        payment_status="PENDING",
        total_amount=50.00,
        expires_at=now + timedelta(hours=48),
    )
    db_session.add(reservation)
    db_session.flush()

    res_item = ReservationItem(
        reservation_id=reservation.id,
        variant_id=variant.id,
        quantity=2,
    )
    db_session.add(res_item)
    db_session.commit()

    # 2. Check pending reservations in branch
    resp_pending = client.get(
        f"/api/v1/payments/pending-reservations?branch_id={branch.id}",
        headers=headers,
    )
    assert resp_pending.status_code == 200
    pending_list = resp_pending.json()
    assert any(p["reservation_code"] == "RSV-TEST-POS" for p in pending_list)

    # 3. Create a payment in Caja for this reservation
    resp_create = client.post(
        "/api/v1/payments",
        json={
            "branch_id": branch.id,
            "reservation_id": reservation.id,
            "customer_name": customer.full_name,
            "concept": "Cobro de Reserva RSV-TEST-POS en caja",
            "amount": 50.00,
            "currency": "EUR",
            "payment_type": "EFECTIVO",
            "notes": "Cliente paga en billetes en mostrador",
        },
        headers=headers,
    )
    assert resp_create.status_code == 201
    payment_data = resp_create.json()
    payment_id = payment_data["id"]
    assert payment_data["status"] == "PENDING"

    # Prior to payment, no EXIT movement exists for RSV-TEST-POS
    exit_before = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.reference_number == "RSV-TEST-POS")
        .first()
    )
    assert exit_before is None

    # 4. Process Cash Payment in Caja
    resp_cash = client.post(
        f"/api/v1/payments/{payment_id}/cash",
        json={"notes": "Cobrado en caja 1"},
        headers=headers,
    )
    assert resp_cash.status_code == 200
    paid_payment = resp_cash.json()
    assert paid_payment["status"] == "PAID"
    assert paid_payment["payment_type"] == "EFECTIVO"
    assert "Caja Local" in paid_payment["reference"]

    # 5. Verify that now, and only now, EXIT movement was created in inventory_movements
    db_session.expire_all()
    exit_after = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.reference_number == "RSV-TEST-POS")
        .first()
    )
    assert exit_after is not None
    assert exit_after.type == MovementType.EXIT.value
    assert exit_after.payment_method == "EFECTIVO"
    assert exit_after.payment_status == "PAID"
    assert exit_after.quantity == 2

    # Verify reservation is COMPLETED and PAID
    updated_res = db_session.query(Reservation).filter(Reservation.id == reservation.id).first()
    assert updated_res.status == "COMPLETED"
    assert updated_res.payment_status == "PAID"


def test_pos_paypal_checkout_flow(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    branch, customer, variant = _setup_catalog(db_session)

    # 1. Create a manual counter payment for PayPal
    resp_create = client.post(
        "/api/v1/payments",
        json={
            "branch_id": branch.id,
            "customer_name": "Juan Perez",
            "concept": "Venta directa accesorios",
            "amount": 15.00,
            "currency": "EUR",
            "payment_type": "PAYPAL",
        },
        headers=headers,
    )
    assert resp_create.status_code == 201
    payment_id = resp_create.json()["id"]

    # 2. Mock PayPal create_order
    mock_order = {"id": "ORDER-MOCK-POS-123", "status": "CREATED", "approval_url": "https://sandbox.paypal.com/checkout"}
    with patch("app.services.paypal_service.PayPalService.create_order", return_value=mock_order):
        resp_order = client.post(
            f"/api/v1/payments/{payment_id}/paypal-order",
            headers=headers,
        )
        assert resp_order.status_code == 200
        assert resp_order.json()["order_id"] == "ORDER-MOCK-POS-123"
        assert resp_order.json()["approval_url"] == "https://sandbox.paypal.com/checkout"

    # 3. Mock PayPal capture_order
    mock_capture = {"status": "COMPLETED", "capture_id": "CAPTURE-POS-999"}
    with patch("app.services.paypal_service.PayPalService.capture_order", return_value=mock_capture):
        resp_capture = client.post(
            f"/api/v1/payments/{payment_id}/paypal-capture?order_id=ORDER-MOCK-POS-123",
            headers=headers,
        )
        assert resp_capture.status_code == 200
        data = resp_capture.json()
        assert data["status"] == "PAID"
        assert data["payment_type"] == "PAYPAL"
        assert data["paypal_capture_id"] == "CAPTURE-POS-999"
