from __future__ import annotations

import io
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.core.dependencies import get_http_fetcher
from app.services.scanner.security import SafeHttpFetcher
from tests.conftest import public_dns_resolver


def _make_png_bytes(size: tuple[int, int] = (32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(20, 120, 110)).save(buf, format="PNG")
    return buf.getvalue()


def test_brand_crud_logo_upload_and_delete_protection(
    auth_client: tuple[TestClient, str],
) -> None:
    client, csrf = auth_client

    # Unauthenticated request rejected.
    anon = TestClient(client.app)
    assert anon.get("/api/v1/brands").status_code == 401

    # Missing CSRF rejected.
    assert client.post("/api/v1/brands", json={"name": "No CSRF"}).status_code == 403

    # Create brand with Taglish + pt-BR languages.
    create_resp = client.post(
        "/api/v1/brands",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Manila SEO Digest",
            "primary_language": "en",
            "secondary_languages": ["fil", "taglish", "pt-BR"],
            "target_country": "Philippines",
            "tone": "Practical and authoritative",
            "target_keywords": ["technical seo", "content ops"],
            "restricted_keywords": ["guaranteed #1"],
            "default_hashtags": ["#SEO", "#ContentHub"],
            "default_cta": "Read the full breakdown.",
        },
    )
    assert create_resp.status_code == 201
    brand = create_resp.json()
    assert brand["slug"] == "manila-seo-digest"
    assert brand["secondary_languages"] == ["fil", "taglish", "pt-BR"]
    brand_id = brand["id"]

    # Duplicate slug rejected with 409.
    dup_resp = client.post(
        "/api/v1/brands",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Manila SEO Digest"},
    )
    assert dup_resp.status_code == 409

    # Upload valid PNG logo via Pillow validator.
    logo_resp = client.post(
        f"/api/v1/brands/{brand_id}/logo",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("logo.png", _make_png_bytes(), "image/png")},
    )
    assert logo_resp.status_code == 200
    assert logo_resp.json()["logo_url"].startswith("/api/v1/media/")

    # Invalid image bytes rejected with 422.
    bad_logo = client.post(
        f"/api/v1/brands/{brand_id}/logo",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("bad.png", b"not-a-real-image", "image/png")},
    )
    assert bad_logo.status_code == 422

    # Update & inspect detail.
    patch_resp = client.patch(
        f"/api/v1/brands/{brand_id}",
        headers={"X-CSRF-Token": csrf},
        json={"tone": "Concise technical", "is_active": True},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["tone"] == "Concise technical"

    detail_resp = client.get(f"/api/v1/brands/{brand_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["websites"] == []

    # Attach website -> deleting brand is blocked (409).
    site_resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "brand_id": brand_id,
            "name": "Main Blog",
            "domain": "https://Example.COM/blog",
            "website_type": "wordpress",
            "article_url_patterns": ["/blog/*", "/articles/*"],
            "excluded_url_patterns": ["/wp-admin/*", "/tag/*"],
        },
    )
    assert site_resp.status_code == 201
    site_id = site_resp.json()["id"]
    assert site_resp.json()["domain"] == "example.com"

    blocked_del = client.delete(f"/api/v1/brands/{brand_id}", headers={"X-CSRF-Token": csrf})
    assert blocked_del.status_code == 409

    # Delete website (has 0 articles), then brand deletes cleanly.
    assert (
        client.delete(f"/api/v1/websites/{site_id}", headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert (
        client.delete(f"/api/v1/brands/{brand_id}", headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )


def test_website_connectivity_autodiscovery_and_dashboard_filtering(
    app: FastAPI,
    test_settings: Settings,
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client

    def mock_handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/":
            return httpx.Response(
                200,
                text=(
                    "<html><head><title>Example WP Blog</title>"
                    "<meta name='generator' content='WordPress 6.7'>"
                    "<link rel='alternate' type='application/rss+xml' href='/feed/' />"
                    "</head><body><h1>Welcome</h1></body></html>"
                ),
            )
        if url == "https://example.com/wp-json/wp/v2/posts?per_page=1":
            return httpx.Response(200, json=[{"link": "https://example.com/blog/hello"}])
        if url == "https://example.com/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
            )
        if url == "https://example.com/llms.txt":
            return httpx.Response(
                200, text="# Example\n- [Guide](https://example.com/blog/guide)\n"
            )
        return httpx.Response(404)

    app.dependency_overrides[get_http_fetcher] = lambda: SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(mock_handler),
    )

    b1 = client.post(
        "/api/v1/brands", headers={"X-CSRF-Token": csrf}, json={"name": "Brand One"}
    ).json()
    b2 = client.post(
        "/api/v1/brands", headers={"X-CSRF-Token": csrf}, json={"name": "Brand Two"}
    ).json()

    s1 = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={"brand_id": b1["id"], "name": "Site One", "domain": "example.com"},
    ).json()

    test_resp = client.post(f"/api/v1/websites/{s1['id']}/test", headers={"X-CSRF-Token": csrf})
    assert test_resp.status_code == 200
    assert test_resp.json()["reachable"] is True
    assert test_resp.json()["detected_website_type"] == "wordpress"

    disc_resp = client.post(
        f"/api/v1/websites/{s1['id']}/discover",
        params={"apply": "true"},
        headers={"X-CSRF-Token": csrf},
    )
    assert disc_resp.status_code == 200
    disc = disc_resp.json()
    assert disc["recommended_method"] == "wordpress"
    assert "https://example.com/feed/" in disc["rss_urls"]
    assert "https://example.com/sitemap.xml" in disc["sitemap_urls"]
    assert "https://example.com/llms.txt" in disc["llms_urls"]

    updated_site = client.get(f"/api/v1/websites/{s1['id']}").json()
    assert updated_site["rss_url"] == "https://example.com/feed/"
    assert updated_site["sitemap_url"] == "https://example.com/sitemap.xml"
    assert updated_site["llms_url"] == "https://example.com/llms.txt"

    # Dashboard metrics reflect real brands/websites and respect brand_id filter.
    all_dash = client.get("/api/v1/dashboard/summary").json()
    assert all_dash["phase2_metrics"]["total_brands"] == 2
    assert all_dash["phase2_metrics"]["active_websites"] == 1

    b2_dash = client.get("/api/v1/dashboard/summary", params={"brand_id": b2["id"]}).json()
    assert b2_dash["phase2_metrics"]["total_brands"] == 1
    assert b2_dash["phase2_metrics"]["active_websites"] == 0

    # Manual scan dispatches without blocking and returns 202.
    scan_resp = client.post(f"/api/v1/websites/{s1['id']}/scan", headers={"X-CSRF-Token": csrf})
    assert scan_resp.status_code == 202
    assert scan_resp.json()["status"] == "pending"
    assert memory_repos["dispatched_scans"] == [scan_resp.json()["id"]]
