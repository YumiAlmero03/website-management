from __future__ import annotations

import io
import json
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.core.dependencies import get_http_fetcher
from app.core.security import decrypt_secret
from app.models.website_content import WebsiteContent
from app.services.scanner.security import SafeHttpFetcher
from tests.conftest import public_dns_resolver


def _png_bytes(width: int = 32, height: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(15, 118, 110)).save(buf, format="PNG")
    return buf.getvalue()


def test_website_categories_and_websites_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/website-categories").status_code == 401
    assert client.get("/api/v1/websites").status_code == 401
    assert client.get("/api/v1/contents").status_code == 401
    assert client.get("/api/v1/websites/1/keyword-bank").status_code == 401
    # Legacy /brands and /articles endpoints must no longer exist.
    assert client.get("/api/v1/brands").status_code == 404
    assert client.get("/api/v1/articles").status_code == 404


def test_keyword_bank_combines_website_content_and_manual_entries(
    auth_client: tuple[TestClient, str], memory_repos: dict[str, Any]
) -> None:
    client, _ = auth_client
    site = memory_repos["websites"].create({
        "name": "Keyword Site", "domain": "keywords.example.com", "keyword_bank": ["Slots Guide"],
    })
    other_site = memory_repos["websites"].create({
        "name": "Other Site", "domain": "other.example.com",
    })

    def create_content(website_id: int, slug: str, keyword: str, **fields: Any) -> WebsiteContent:
        url = f"https://example.com/{slug}"
        return memory_repos["contents"].create({
            "website_id": website_id,
            "title": slug,
            "url": url,
            "canonical_url": url,
            "url_hash": slug,
            "content_hash": slug,
            "keywords": [keyword],
            **fields,
        })

    row = create_content(site.id, "game", "Volatility")
    memory_repos["keyword_approvals"].upsert_keyword(
        website_id=site.id,
        website_content_id=row.id,
        data={"focus_keyphrase": "Golden Lamps slots",
              "secondary_keywords_json": ["SLOTS   GUIDE", "Golden Lamps"]},
    )
    create_content(site.id, "unmapped", "Demo play")
    create_content(site.id, "excluded", "Excluded phrase", is_excluded=True)
    create_content(other_site.id, "other", "Another website's keyword")

    response = client.get(f"/api/v1/websites/{site.id}/keyword-bank")
    assert response.status_code == 200
    assert response.json() == [
        "Demo play", "Golden Lamps", "Golden Lamps slots", "Slots Guide", "Volatility",
    ]


def test_website_category_lifecycle_and_delete_protection(
    auth_client: tuple[TestClient, str],
) -> None:
    client, csrf = auth_client

    # Default seeded categories present without hardcoded enums.
    list_resp = client.get("/api/v1/website-categories")
    assert list_resp.status_code == 200
    names = {c["name"] for c in list_resp.json()["items"]}
    assert {"Sports Web", "Casino", "Brand", "Illegal Brand"}.issubset(names)

    # Create a custom category.
    create_resp = client.post(
        "/api/v1/website-categories",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Affiliate Review", "description": "Comparison portals", "sort_order": 5},
    )
    assert create_resp.status_code == 201
    cat_id = create_resp.json()["id"]
    assert create_resp.json()["slug"] == "affiliate-review"

    # Assign a website to it -> deleting category must be blocked cleanly.
    site_resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Review Hub",
            "brand_name": "ReviewHub",
            "domain": "https://reviewhub.example.com/",
            "category_id": cat_id,
            "primary_language": "en",
        },
    )
    assert site_resp.status_code == 201
    site_id = site_resp.json()["id"]
    assert site_resp.json()["domain"] == "reviewhub.example.com"
    assert site_resp.json()["category_name"] == "Affiliate Review"

    blocked_del = client.delete(
        f"/api/v1/website-categories/{cat_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert blocked_del.status_code == 409

    # Create an unused category -> can archive and delete cleanly.
    unused = client.post(
        "/api/v1/website-categories",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Temporary Tag"},
    ).json()
    arch_resp = client.patch(
        f"/api/v1/website-categories/{unused['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Archived Custom", "is_archived": True},
    )
    assert arch_resp.status_code == 200
    assert arch_resp.json()["is_archived"] is True
    assert (
        client.delete(
            f"/api/v1/website-categories/{unused['id']}",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )

    # Delete website (has no content yet), then delete category.
    assert (
        client.delete(
            f"/api/v1/websites/{site_id}",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/website-categories/{cat_id}",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )


def test_website_registration_rules_sources_discovery_and_logo_upload(
    app: Any,
    test_settings: Settings,
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client

    homepage_html = """<!doctype html><html><head>
      <title>Bygame Casino — Play Responsibly</title>
      <meta name="generator" content="Nuxt 3" />
      <link rel="alternate" type="application/rss+xml" href="/feed.xml" />
    </head><body><div id="__nuxt">Home</div></body></html>"""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://bygame.example.com/":
            return httpx.Response(200, text=homepage_html, headers={"Content-Type": "text/html"})
        if url == "https://bygame.example.com/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nSitemap: https://bygame.example.com/sitemap.xml\n"
            )
        if url == "https://bygame.example.com/sitemap.xml":
            return httpx.Response(
                200, text="<urlset><url><loc>https://bygame.example.com/</loc></url></urlset>"
            )
        if url == "https://bygame.example.com/feed.xml":
            return httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>")
        return httpx.Response(404)

    app.dependency_overrides[get_http_fetcher] = lambda: SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(mock_handler),
    )

    # Reject private/loopback domain SSRF attempt
    ssrf_resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Internal", "domain": "127.0.0.1"},
    )
    assert ssrf_resp.status_code == 422

    # Register website directly with full URL, merged brand profile, and custom crawl settings.
    create_resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Bygame Casino",
            "brand_name": "Bygame",
            "domain": "https://bygame.example.com/",
            "category_id": 2,
            "primary_language": "Taglish",
            "target_country": "Philippines",
            "website_type": "nuxt",
            "tone": "Energetic & Responsible",
            "target_keywords": ["casino", "slots"],
            "default_hashtags": ["#Bygame", "#Gaming"],
            "writing_guidelines": "Keep copy engaging and accurate.",
            "crawl_batch_size": 50,
            "crawl_max_urls_per_run": 500,
        },
    )
    assert create_resp.status_code == 201
    site = create_resp.json()
    site_id = site["id"]
    assert site["brand_name"] == "Bygame"
    assert site["primary_language"] == "Taglish"
    assert site["category_name"] == "Casino"
    assert site["crawl_batch_size"] == 50

    # Upload logo directly to Website Management.
    logo_resp = client.post(
        f"/api/v1/websites/{site_id}/logo",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("logo.png", _png_bytes(48, 48), "image/png")},
    )
    assert logo_resp.status_code == 200
    assert logo_resp.json()["logo_url"].startswith("/api/v1/media/")

    # Connectivity & auto-discovery detect Nuxt, RSS, Sitemap, and save source rows.
    conn_resp = client.post(f"/api/v1/websites/{site_id}/test", headers={"X-CSRF-Token": csrf})
    assert conn_resp.status_code == 200
    assert conn_resp.json()["reachable"] is True
    assert conn_resp.json()["detected_website_type"] == "nuxt"

    disc_resp = client.post(
        f"/api/v1/websites/{site_id}/discover?apply=true",
        headers={"X-CSRF-Token": csrf},
    )
    assert disc_resp.status_code == 200
    assert "https://bygame.example.com/sitemap.xml" in disc_resp.json()["sitemap_urls"]
    assert "https://bygame.example.com/feed.xml" in disc_resp.json()["rss_urls"]

    sources = client.get(f"/api/v1/websites/{site_id}/sources").json()
    assert len(sources) >= 3
    rss_src = next(s for s in sources if s["source_type"] == "rss")
    toggled = client.patch(
        f"/api/v1/websites/{site_id}/sources/{rss_src['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"is_enabled": False},
    )
    assert toggled.status_code == 200
    assert toggled.json()["is_enabled"] is False

    # URL classification rules CRUD + invalid regex rejection
    bad_rule = client.post(
        f"/api/v1/websites/{site_id}/rules",
        headers={"X-CSRF-Token": csrf},
        json={"pattern": "[unclosed", "target_content_type": "page", "match_mode": "regex"},
    )
    assert bad_rule.status_code == 422

    rule = client.post(
        f"/api/v1/websites/{site_id}/rules",
        headers={"X-CSRF-Token": csrf},
        json={
            "pattern": "/game/*",
            "target_content_type": "page",
            "match_mode": "glob",
            "priority": 10,
            "notes": "Treat game detail URLs as Pages",
        },
    )
    assert rule.status_code == 201
    rule_id = rule.json()["id"]
    assert len(client.get(f"/api/v1/websites/{site_id}/rules").json()) == 1

    upd_rule = client.patch(
        f"/api/v1/websites/{site_id}/rules/{rule_id}",
        headers={"X-CSRF-Token": csrf},
        json={"target_content_type": "custom", "priority": 5},
    )
    assert upd_rule.status_code == 200
    assert upd_rule.json()["target_content_type"] == "custom"

    # Dashboard metrics filter cleanly by category_id
    dash_cat2 = client.get("/api/v1/dashboard/summary", params={"category_id": 2}).json()
    assert dash_cat2["phase2_metrics"]["active_websites"] == 1
    dash_cat1 = client.get("/api/v1/dashboard/summary", params={"category_id": 1}).json()
    assert dash_cat1["phase2_metrics"]["active_websites"] == 0

    # Clean delete rule works
    assert (
        client.delete(
            f"/api/v1/websites/{site_id}/rules/{rule_id}",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )

    # Triggering scan dispatches without error
    scan_resp = client.post(
        f"/api/v1/websites/{site_id}/scan",
        headers={"X-CSRF-Token": csrf},
        json={"scan_mode": "full"},
    )
    assert scan_resp.status_code == 202
    assert scan_resp.json()["scan_mode"] == "full"
    assert memory_repos["dispatched_scans"] == [scan_resp.json()["id"]]


def test_google_index_service_account_upload_is_encrypted_and_revocable(
    test_settings: Settings,
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client
    created = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Index Test", "domain": "index-test.example.com"},
    )
    assert created.status_code == 201
    website_id = created.json()["id"]
    property_update = client.patch(
        f"/api/v1/websites/{website_id}",
        headers={"X-CSRF-Token": csrf},
        json={"gsc_property_url": "https://index-test.example.com/"},
    )
    assert property_update.status_code == 200
    assert property_update.json()["gsc_property_url"] == "https://index-test.example.com/"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    raw_json = json.dumps({
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": private_key_pem,
        "client_email": "indexer@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "token_uri": "https://oauth2.googleapis.com/token",
    })

    upload = client.post(
        f"/api/v1/websites/{website_id}/google-index-service-account",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("service-account.json", raw_json.encode(), "application/json")},
    )
    assert upload.status_code == 200
    assert upload.json()["gsc_service_account_configured"] is True
    assert "private_key" not in upload.text
    saved_site = memory_repos["websites"].get_by_id(website_id)
    assert saved_site.encrypted_gsc_service_account_json != raw_json
    assert (
        decrypt_secret(
            saved_site.encrypted_gsc_service_account_json,
            test_settings.app_encryption_key,
        )
        == raw_json
    )

    rejected = client.post(
        f"/api/v1/websites/{website_id}/google-index-service-account",
        headers={"X-CSRF-Token": csrf},
        files={
            "file": (
                "service-account.json",
                json.dumps({
                    "type": "service_account",
                    "client_email": "indexer@test-project.iam.gserviceaccount.com",
                    "private_key": private_key_pem,
                    "token_uri": "https://attacker.example/token",
                }).encode(),
                "application/json",
            )
        },
    )
    assert rejected.status_code == 422
    assert saved_site.encrypted_gsc_service_account_json is not None

    removed = client.delete(
        f"/api/v1/websites/{website_id}/google-index-service-account",
        headers={"X-CSRF-Token": csrf},
    )
    assert removed.status_code == 200
    assert removed.json()["gsc_service_account_configured"] is False
    assert saved_site.encrypted_gsc_service_account_json is None
