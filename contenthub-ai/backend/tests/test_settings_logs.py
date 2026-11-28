from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.security import decrypt_secret


def test_settings_require_auth_and_csrf_and_encrypt_secrets(
    client: TestClient,
    auth_client: tuple[TestClient, str],
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    authed, csrf = auth_client

    # Initial GET returns full Phase 1 catalog defaults.
    resp = authed.get("/api/v1/settings")
    assert resp.status_code == 200
    payload = resp.json()
    by_key = {item["key"]: item for item in payload["items"]}
    assert by_key["app.timezone"]["value"] == "Asia/Manila"
    assert by_key["publishing.default_mode"]["value"] == "semi_automatic"
    assert by_key["security.webhook_signing_secret"]["is_secret"] is True
    assert by_key["security.webhook_signing_secret"]["has_value"] is False

    # PUT without CSRF fails 403.
    no_csrf = authed.put(
        "/api/v1/settings",
        json={"items": [{"key": "backups.retention_days", "value": 30}]},
    )
    assert no_csrf.status_code == 403

    # PUT with invalid timezone fails 422.
    bad_tz = authed.put(
        "/api/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={"items": [{"key": "app.timezone", "value": "Mars/Olympus"}]},
    )
    assert bad_tz.status_code == 422

    # PUT with CPU warning >= critical fails 422.
    bad_cpu = authed.put(
        "/api/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={
            "items": [
                {"key": "resources.cpu_warning_percent", "value": 90},
                {"key": "resources.cpu_critical_percent", "value": 85},
            ]
        },
    )
    assert bad_cpu.status_code == 422

    # Valid update persists standard + Fernet-encrypted secret without returning plaintext.
    update_resp = authed.put(
        "/api/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={
            "items": [
                {"key": "backups.retention_days", "value": 30},
                {"key": "security.webhook_signing_secret", "value": "top-secret-signing-key"},
            ]
        },
    )
    assert update_resp.status_code == 200
    updated_by_key = {item["key"]: item for item in update_resp.json()["items"]}
    assert updated_by_key["backups.retention_days"]["value"] == 30
    assert updated_by_key["security.webhook_signing_secret"]["value"] is None
    assert updated_by_key["security.webhook_signing_secret"]["has_value"] is True

    stored_secret_row = memory_repos["settings"].get_by_key("security.webhook_signing_secret")
    assert stored_secret_row is not None
    assert stored_secret_row.encrypted_value is not None
    assert "top-secret-signing-key" not in stored_secret_row.encrypted_value
    assert (
        decrypt_secret(stored_secret_row.encrypted_value, test_settings.app_encryption_key)
        == "top-secret-signing-key"
    )

    # Unauthenticated access to settings & logs is rejected.
    anon_client = TestClient(authed.app)
    assert anon_client.get("/api/v1/settings").status_code == 401
    assert anon_client.get("/api/v1/logs/activity").status_code == 401
    assert anon_client.get("/api/v1/logs/background").status_code == 401


def test_activity_logs_pagination_filtering_and_redaction(
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
) -> None:
    authed, _csrf = auth_client

    memory_repos["activities"].create(
        user_id=1,
        actor_type="admin",
        category="settings",
        action="settings.test_secret",
        level="warning",
        message="Updated setting with token=should_never_leak",
        metadata={"api_key": "raw-api-key", "setting": "backups.retention_days"},
    )

    resp = authed.get(
        "/api/v1/logs/activity", params={"category": "settings", "page": 1, "page_size": 10}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["total_items"] >= 1
    first = data["items"][0]
    assert "should_never_leak" not in first["message"]
    assert first["metadata"]["api_key"] == "[REDACTED]"
    assert first["metadata"]["setting"] == "backups.retention_days"

    background = authed.get("/api/v1/logs/background")
    assert background.status_code == 200
    names = {item["function"] for item in background.json()["items"]}
    assert names == {
        "Website scanning",
        "AI content generation",
        "Social publishing",
        "Google indexing",
    }
