from __future__ import annotations

from fastapi.testclient import TestClient


def test_public_liveness_health_returns_minimal_safe_info(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "ContentHub AI"
    assert body["timezone"] == "Asia/Manila"
    assert "db_password" not in body
    assert "resources" not in body
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


def test_protected_health_and_dashboard_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/health/db").status_code == 401
    assert client.get("/api/v1/health/system").status_code == 401
    assert client.get("/api/v1/dashboard/summary").status_code == 401


def test_authenticated_health_and_dashboard_return_real_phase2_metrics(
    auth_client: tuple[TestClient, str],
) -> None:
    client, _csrf = auth_client

    db_resp = client.get("/api/v1/health/db")
    assert db_resp.status_code == 200
    db_body = db_resp.json()
    assert db_body["connected"] is True
    assert db_body["server_version"] == "8.0.45"
    assert db_body["character_set"] == "utf8mb4"
    assert db_body["innodb_available"] is True

    sys_resp = client.get("/api/v1/health/system")
    assert sys_resp.status_code == 200
    sys_body = sys_resp.json()
    assert sys_body["resources"]["cpu_cores"] >= 1
    assert sys_body["resources"]["ram_total_mb"] > 0
    assert sys_body["resources"]["guardian_status"] in {"normal", "warning", "critical"}
    assert len(sys_body["storage_paths"]) == 5

    dash_resp = client.get("/api/v1/dashboard/summary")
    assert dash_resp.status_code == 200
    dash = dash_resp.json()
    assert dash["current_phase"] == 4
    assert dash["phase1_counts"]["active_sessions"] == 1
    assert dash["phase2_metrics"]["total_categories"] == 8
    assert dash["phase2_metrics"]["active_websites"] == 0
    assert dash["phase2_metrics"]["total_contents"] == 0
    assert dash["phase4_metrics"]["published_today"] == 0

    active_modules = [m for m in dash["modules"] if m["status"] == "active"]
    future_modules = [m for m in dash["modules"] if m["status"] == "not_implemented"]
    assert {m["key"] for m in active_modules} == {
        "websites",
        "content_library",
        "content_approval",
        "ai_management",
        "social_media",
        "connected_accounts",
        "publishing_calendar",
    }
    assert {m["key"] for m in future_modules} == {
        "editorial_planner",
        "articles",
        "automation",
        "analytics",
    }
