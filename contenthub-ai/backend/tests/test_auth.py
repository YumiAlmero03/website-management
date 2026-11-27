from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.dependencies import get_user_repo


def test_auth_status_uninitialized_and_registration_disabled(client: TestClient) -> None:
    status_resp = client.get("/api/v1/auth/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["admin_initialized"] is False
    assert body["authenticated"] is False
    assert body["database_connected"] is True
    assert body["registration_enabled"] is False

    # Public registration endpoints must not exist.
    assert client.post("/api/v1/auth/register", json={}).status_code == 404
    assert client.post("/api/v1/auth/signup", json={}).status_code == 404


def test_auth_status_handles_database_unavailable_gracefully(app: FastAPI) -> None:
    class FailingUserRepo:
        def count_all(self) -> int:
            raise OperationalError("SELECT 1", {}, Exception("Connection refused"))

    app.dependency_overrides[get_user_repo] = lambda: FailingUserRepo()
    client = TestClient(app)
    resp = client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    assert resp.json()["database_connected"] is False
    assert resp.json()["admin_initialized"] is False
    assert resp.json()["authenticated"] is False


def test_login_session_csrf_and_logout_lifecycle(
    client: TestClient,
    seeded_admin: dict[str, str],
) -> None:
    # Unauthenticated access to /me is rejected.
    assert client.get("/api/v1/auth/me").status_code == 401

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_admin["email"], "password": seeded_admin["password"]},
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert data["user"]["email"] == seeded_admin["email"]
    assert data["csrf_token"]
    set_cookie = login_resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()

    # Authenticated /me returns active session and same CSRF token.
    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == seeded_admin["email"]
    assert me_resp.json()["csrf_token"] == data["csrf_token"]

    # Mutating logout without CSRF token is rejected with 403.
    bad_logout = client.post("/api/v1/auth/logout")
    assert bad_logout.status_code == 403
    assert bad_logout.json()["code"] == "CSRF_INVALID"

    # Logout with valid CSRF token succeeds and revokes session.
    good_logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": data["csrf_token"]},
    )
    assert good_logout.status_code == 200

    # Revoked session cannot access protected endpoint.
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rate_limiting_blocks_repeated_failures(
    client: TestClient,
    seeded_admin: dict[str, str],
) -> None:
    for _ in range(3):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": seeded_admin["email"], "password": "WrongPassword!999"},
        )
        assert resp.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_admin["email"], "password": seeded_admin["password"]},
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) >= 1


def test_expired_session_and_inactive_user_rejected(
    client: TestClient,
    seeded_admin: dict[str, str],
    memory_repos: dict[str, object],
) -> None:
    from datetime import timedelta

    from app.models.base import utc_now_naive

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_admin["email"], "password": seeded_admin["password"]},
    )
    assert login_resp.status_code == 200
    sessions_repo = memory_repos["sessions"]
    for sess in sessions_repo._items.values():  # type: ignore[attr-defined]
        sess.expires_at = utc_now_naive() - timedelta(minutes=1)

    assert client.get("/api/v1/auth/me").status_code == 401

    user = memory_repos["users"].get_by_email(seeded_admin["email"])  # type: ignore[attr-defined]
    assert user is not None
    user.is_active = False
    inactive_resp = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_admin["email"], "password": seeded_admin["password"]},
    )
    assert inactive_resp.status_code == 401
    assert inactive_resp.json()["code"] == "ACCOUNT_INACTIVE"
