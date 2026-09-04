import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


def test_forgot_password_registered_user(client, db_session):
    # Register a user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "reset@example.com",
            "password": "OldPassword123!",
            "full_name": "Reset User",
        },
    )

    with patch("app.services.email_service.EmailService.send_reset_token_email", return_value=True) as mock_send:
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "reset@example.com"},
        )
        assert response.status_code == 200
        assert "recibirás un código" in response.json()["message"]
        mock_send.assert_called_once()

    # Check token in database
    user = db_session.query(User).filter(User.email == "reset@example.com").first()
    token_record = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .first()
    )
    assert token_record is not None
    assert len(token_record.token) == 6
    assert token_record.is_used is False


def test_forgot_password_unregistered_email(client):
    # Non-existent email should return 200 (anti-enumeration) without sending email
    with patch("app.services.email_service.EmailService.send_reset_token_email") as mock_send:
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
        assert response.status_code == 200
        mock_send.assert_not_called()


def test_reset_password_success(client, db_session):
    # 1. Register
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "change@example.com",
            "password": "OldPassword123!",
            "full_name": "Change User",
        },
    )

    # 2. Request reset
    with patch("app.services.email_service.EmailService.send_reset_token_email", return_value=True):
        client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "change@example.com"},
        )

    # 3. Get token from DB
    user = db_session.query(User).filter(User.email == "change@example.com").first()
    token_record = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id, PasswordResetToken.is_used == False)
        .first()
    )
    token = token_record.token

    # 4. Reset password
    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "change@example.com",
            "token": token,
            "new_password": "NewPassword456!",
        },
    )
    assert response.status_code == 200
    assert "actualizada exitosamente" in response.json()["message"]

    # 5. Old password no longer works
    login_old = client.post(
        "/api/v1/auth/login",
        json={"email": "change@example.com", "password": "OldPassword123!"},
    )
    assert login_old.status_code == 401

    # 6. New password works
    login_new = client.post(
        "/api/v1/auth/login",
        json={"email": "change@example.com", "password": "NewPassword456!"},
    )
    assert login_new.status_code == 200
    assert "access_token" in login_new.json()


def test_reset_password_single_use(client, db_session):
    # Register
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "singleuse@example.com",
            "password": "Password123!",
            "full_name": "Single User",
        },
    )

    with patch("app.services.email_service.EmailService.send_reset_token_email", return_value=True):
        client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "singleuse@example.com"},
        )

    user = db_session.query(User).filter(User.email == "singleuse@example.com").first()
    token_record = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .first()
    )
    token = token_record.token

    # Use first time: success
    res1 = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "singleuse@example.com",
            "token": token,
            "new_password": "NewPassword1!",
        },
    )
    assert res1.status_code == 200

    # Use second time: should fail
    res2 = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "singleuse@example.com",
            "token": token,
            "new_password": "AnotherPassword2!",
        },
    )
    assert res2.status_code == 400


def test_reset_password_expired_token(client, db_session):
    # Register
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "expired@example.com",
            "password": "Password123!",
            "full_name": "Expired User",
        },
    )

    with patch("app.services.email_service.EmailService.send_reset_token_email", return_value=True):
        client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "expired@example.com"},
        )

    user = db_session.query(User).filter(User.email == "expired@example.com").first()
    token_record = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .first()
    )
    # Expire the token by setting expires_at to 10 minutes ago
    token_record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "expired@example.com",
            "token": token_record.token,
            "new_password": "NewPassword123!",
        },
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()
