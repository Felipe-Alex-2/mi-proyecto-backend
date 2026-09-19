import pytest
from datetime import datetime, timezone, timedelta
from app.models.branch import Branch
from app.models.category import Category
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.size import Size
from app.models.color import Color
from app.models.stock import Stock
from app.models.reservation import Reservation
from app.models.reservation_item import ReservationItem
from app.models.payment import Payment
from app.models.user import User, UserRole
from app.core.security import get_password_hash, create_access_token


def _setup_scenario(db_session):
    branch = Branch(name="Sucursal Norte", city="Santa Cruz", address="Av. Cristo Redentor 456", is_active=True)
    cat = Category(name="Vestidos")
    sz = Size(name="S", code="S-VEST")
    col = Color(name="Azul Marino", hex_code="#000080")
    customer = User(
        email="cliente_notif@test.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="Maria Notificaciones",
        role=UserRole.CUSTOMER.value,
        is_active=True,
    )
    db_session.add_all([branch, cat, sz, col, customer])
    db_session.commit()

    prod = Product(name="Vestido de Noche & Gala <Lujo>", price=60.0, category_id=cat.id, is_active=True)
    db_session.add(prod)
    db_session.commit()

    variant = ProductVariant(product_id=prod.id, size_id=sz.id, color_id=col.id, sku="SKU-VEST-01")
    db_session.add(variant)
    db_session.commit()

    stock = Stock(variant_id=variant.id, branch_id=branch.id, quantity=10)
    db_session.add(stock)
    db_session.commit()

    return branch, customer, variant


def test_invoice_pdf_download_with_query_token_and_special_chars(client, admin_token, db_session):
    branch, customer, variant = _setup_scenario(db_session)

    payment = Payment(
        payment_code="PAY-INV-SPECIAL",
        branch_id=branch.id,
        customer_id=customer.id,
        customer_name="Juan & Maria <VIP>",
        customer_email="juan_maria@test.com",
        concept="Vestido & Accesorios <Especial>",
        amount=120.00,
        currency="USD",
        payment_type="PAYPAL",
        status="PAID",
        notes="Comentarios con & y < y > especiales",
    )
    db_session.add(payment)
    db_session.commit()

    # 1. Test downloading with query parameter ?token=
    resp = client.get(f"/api/v1/payments/{payment.id}/invoice-pdf?token={admin_token}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 1000

    # 2. Test downloading with standard Bearer header
    resp2 = client.get(
        f"/api/v1/payments/{payment.id}/invoice-pdf",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 200
    assert resp2.content.startswith(b"%PDF")


def test_reservation_accepted_triggers_notification_and_badge(client, admin_token, db_session):
    branch, customer, variant = _setup_scenario(db_session)
    now = datetime.now(timezone.utc)

    # 1. Create a reservation for customer
    reservation = Reservation(
        reservation_code="RSV-NOTIF-01",
        customer_id=customer.id,
        branch_id=branch.id,
        status="PENDING",
        payment_method="EFECTIVO",
        payment_status="PENDING",
        total_amount=60.00,
        expires_at=now + timedelta(hours=48),
    )
    db_session.add(reservation)
    db_session.commit()

    res_item = ReservationItem(
        reservation_id=reservation.id,
        variant_id=variant.id,
        quantity=1,
    )
    db_session.add(res_item)
    db_session.commit()

    # Customer token
    customer_token = create_access_token(customer.id)
    cust_headers = {"Authorization": f"Bearer {customer_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Verify initial unread count is 0
    resp_count_0 = client.get("/api/v1/notifications/unread-count", headers=cust_headers)
    assert resp_count_0.status_code == 200
    assert resp_count_0.json()["unread_count"] == 0

    # 2. Staff confirms/accepts the reservation from Web (CU13)
    resp_confirm = client.patch(
        f"/api/v1/reservations/{reservation.id}/status",
        json={"status": "CONFIRMED", "staff_notes": "Aceptado en tienda"},
        headers=admin_headers,
    )
    assert resp_confirm.status_code == 200
    assert resp_confirm.json()["status"] == "CONFIRMED"

    # 3. Customer checks unread count -> should be 1
    resp_count_1 = client.get("/api/v1/notifications/unread-count", headers=cust_headers)
    assert resp_count_1.status_code == 200
    assert resp_count_1.json()["unread_count"] >= 1

    # 4. Customer fetches notifications list
    resp_list = client.get("/api/v1/notifications", headers=cust_headers)
    assert resp_list.status_code == 200
    notifs = resp_list.json()
    assert len(notifs) >= 1
    target_notif = next((n for n in notifs if n["reservation_id"] == reservation.id), None)
    assert target_notif is not None
    assert "aceptado" in target_notif["title"].lower() or "aceptado" in target_notif["message"].lower()
    assert target_notif["is_read"] is False

    # 5. Customer marks notification as read
    resp_read = client.patch(f"/api/v1/notifications/{target_notif['id']}/read", headers=cust_headers)
    assert resp_read.status_code == 200
    assert resp_read.json()["is_read"] is True

    # 6. Unread count decreases
    resp_count_after = client.get("/api/v1/notifications/unread-count", headers=cust_headers)
    assert resp_count_after.json()["unread_count"] == 0


def test_paypal_capture_request_accepts_order_id_alias(client, admin_token, db_session):
    branch, customer, variant = _setup_scenario(db_session)
    now = datetime.now(timezone.utc)

    # Pre-create reservation with paypal_order_id
    reservation = Reservation(
        reservation_code="RSV-PAYPAL-ALIAS",
        customer_id=customer.id,
        branch_id=branch.id,
        status="PENDING",
        payment_method="PAYPAL",
        payment_status="PENDING",
        paypal_order_id="ORDER-12345",
        total_amount=60.00,
        expires_at=now + timedelta(hours=48),
    )
    db_session.add(reservation)
    db_session.commit()

    # Mock PayPal capture to avoid live network call
    from unittest.mock import patch
    with patch("app.services.paypal_service.PayPalService.capture_order") as mock_capture:
        mock_capture.return_value = {
            "status": "COMPLETED",
            "capture_id": "CAP-998877",
        }

        # Mobile sends {"order_id": "ORDER-12345"}
        resp = client.post(
            "/api/v1/reservations/paypal-capture",
            json={"order_id": "ORDER-12345"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert data["capture_id"] == "CAP-998877"
        assert data["reservation"]["payment_status"] == "PAID"
