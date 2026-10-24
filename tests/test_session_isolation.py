from datetime import datetime, timezone

from app.nucleo import seguridad as security


def test_tokens_for_same_account_are_unique_even_in_same_second(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(security, "datetime", FixedDatetime)
    for create in (security.create_access_token, security.create_refresh_token):
        web = create("same-user")
        pwa = create("same-user")
        assert web != pwa


def test_logout_does_not_revoke_another_login(client):
    credentials = {"email": "sessions@example.com", "password": "Password123!"}
    assert client.post(
        "/api/v1/auth/register", json={**credentials, "full_name": "Session Usuario"}
    ).status_code == 201
    web = client.post("/api/v1/auth/login", json=credentials).json()
    pwa = client.post("/api/v1/auth/login", json=credentials).json()
    web_headers = {"Authorization": f"Bearer {web['access_token']}"}
    pwa_headers = {"Authorization": f"Bearer {pwa['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=web_headers).status_code == 200
    assert client.get("/api/v1/users/me", headers=web_headers).status_code == 401
    assert client.get("/api/v1/users/me", headers=pwa_headers).status_code == 200
