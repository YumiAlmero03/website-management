from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.dependencies import get_publisher_registry
from app.core.security import decrypt_secret, hash_token
from app.models.base import utc_now_naive
from app.services.publishers.base import TrustedPublisherHttpClient
from app.services.publishers.exceptions import PublisherError
from app.services.publishers.registry import PublisherAdapterRegistry


def _create_website(client: TestClient, csrf: str, name: str = "Bygame", domain: str = "bygame.ph"):
    cat_id = client.get("/api/v1/website-categories").json()["items"][0]["id"]
    resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "category_id": cat_id,
            "name": name,
            "brand_name": name,
            "domain": domain,
            "website_type": "wordpress",
            "discovery_method": "auto",
            "primary_language": "English",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_profile(
    client: TestClient,
    csrf: str,
    website_id: int,
    *,
    platform_key: str,
    profile_name: str,
    publishing_method: str = "api",
) -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/websites/{website_id}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": platform_key,
            "profile_name": profile_name,
            "publishing_method": publishing_method,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_trusted_publisher_http_client_blocks_untrusted_hosts() -> None:
    client = TrustedPublisherHttpClient(
        allowed_hosts=frozenset({"graph.facebook.com"}),
        timeout_seconds=10.0,
    )
    try:
        client.request("GET", "http://graph.facebook.com/v27.0/me")
        raise AssertionError("Expected PublisherError for plain HTTP URL")
    except PublisherError as exc:
        assert exc.code == "UNTRUSTED_PROVIDER_HOST"

    try:
        client.request("GET", "https://evil.attacker.example/steal")
        raise AssertionError("Expected PublisherError for non-allowlisted host")
    except PublisherError as exc:
        assert exc.code == "UNTRUSTED_PROVIDER_HOST"


def test_publishing_preferences_and_auto_publish_safeguard(
    auth_client: tuple[TestClient, str],
) -> None:
    client, csrf = auth_client
    site = _create_website(client, csrf)
    prof = _create_profile(
        client, csrf, site["id"], platform_key="facebook", profile_name="Pref Test Page"
    )

    # Auto-publish remains strictly disabled in Phase 4
    bad_auto = client.patch(
        f"/api/v1/social-profiles/{prof['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"auto_publish_enabled": True},
    )
    assert bad_auto.status_code == 422

    # Invalid IANA timezone rejected cleanly
    bad_tz = client.patch(
        f"/api/v1/social-profiles/{prof['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"display_timezone": "Invalid/Mars_City"},
    )
    assert bad_tz.status_code == 422

    # Valid Phase 4 preferences persisted cleanly
    updated = client.patch(
        f"/api/v1/social-profiles/{prof['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "publishing_enabled": True,
            "display_timezone": "Asia/Manila",
            "preferred_publishing_days": ["Mon", "Wed", "Fri"],
            "preferred_publishing_times": ["09:00", "18:30"],
            "daily_publishing_limit": 5,
            "min_interval_minutes": 30,
            "require_approval_before_publish": True,
            "default_media_required": True,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["publishing_enabled"] is True
    assert body["effective_timezone"] == "Asia/Manila"
    assert body["preferred_publishing_days"] == ["mon", "wed", "fri"]
    assert body["preferred_publishing_times"] == ["09:00", "18:30"]
    assert body["daily_publishing_limit"] == 5
    assert body["min_interval_minutes"] == 30
    assert body["default_media_required"] is True


def test_oauth_start_security_replay_and_expiry(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.x.com" and request.url.path == "/2/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "token_type": "bearer",
                    "access_token": "x_access_tok_secret_123",
                    "refresh_token": "x_refresh_tok_secret_456",
                    "expires_in": 7200,
                    "scope": "tweet.write tweet.read users.read offline.access",
                },
            )
        if request.url.host == "api.x.com" and request.url.path == "/2/users/me":
            return httpx.Response(
                200,
                json={"data": {"id": "19901", "username": "bygame_ph", "name": "Bygame PH"}},
            )
        raise AssertionError(f"Unexpected external URL: {request.method} {request.url}")

    app.dependency_overrides[get_publisher_registry] = lambda: PublisherAdapterRegistry(
        settings=test_settings, transport=httpx.MockTransport(handler)
    )
    site = _create_website(client, csrf)
    prof = _create_profile(
        client, csrf, site["id"], platform_key="twitter", profile_name="Bygame X"
    )

    # Untrusted OAuth redirect host rejected
    bad_redirect = client.post(
        f"/api/v1/social-profiles/{prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "oauth",
            "app_id": "x-client-id-1",
            "app_secret": "x-client-secret-1",
            "redirect_uri": "https://evil.example.org/cb",
        },
    )
    assert bad_redirect.status_code == 422

    # Valid OAuth start generates PKCE S256 URL + hashed state
    ok_start = client.post(
        f"/api/v1/social-profiles/{prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "oauth",
            "app_id": "x-client-id-1",
            "app_secret": "x-client-secret-1",
            "redirect_uri": "http://127.0.0.1:3100/connected-accounts?oauth_callback=1",
        },
    )
    assert ok_start.status_code == 200, ok_start.text
    start_body = ok_start.json()
    assert start_body["action"] == "oauth_redirect"
    parsed_qs = parse_qs(urlparse(start_body["authorization_url"]).query)
    assert parsed_qs["code_challenge_method"] == ["S256"]
    raw_state = parsed_qs["state"][0]

    # Complete OAuth callback exchanges PKCE code and stores Fernet-encrypted secrets
    done = client.post(
        f"/api/v1/social-profiles/{prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": raw_state, "code": "auth-code-x-123"},
    )
    assert done.status_code == 200, done.text
    conn_data = done.json()
    # X 7200s token is within the 7-day warning window so UI surfaces expiring_soon + expires_soon
    assert conn_data["connection_status"] == "expiring_soon"
    assert conn_data["expires_soon"] is True
    assert conn_data["external_username"] == "bygame_ph"
    # Pay-per-use not explicitly opted in -> manual_only eligibility
    assert conn_data["eligibility_status"] == "manual_only"
    assert "x_access_tok_secret_123" not in json.dumps(conn_data)

    # Verify raw token stored encrypted in repository
    stored_prof = memory_repos["social_profiles"].get_by_id(prof["id"])
    assert stored_prof is not None
    assert stored_prof.encrypted_access_token != "x_access_tok_secret_123"
    assert (
        decrypt_secret(stored_prof.encrypted_access_token, test_settings.app_encryption_key)
        == "x_access_tok_secret_123"
    )

    # Enabling paid API opt-in makes X profile eligible on verify
    paid = client.post(
        f"/api/v1/social-profiles/{prof['id']}/paid-policy",
        headers={"X-CSRF-Token": csrf},
        json={"allow_paid_publishing": True},
    )
    assert paid.status_code == 200
    assert paid.json()["allow_paid_publishing"] is True
    assert paid.json()["eligibility_status"] == "eligible"

    # Replaying consumed OAuth state fails with 409 Conflict
    replay = client.post(
        f"/api/v1/social-profiles/{prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": raw_state, "code": "auth-code-x-123"},
    )
    assert replay.status_code == 409

    # Expired OAuth state rejected cleanly
    exp_start = client.post(
        f"/api/v1/social-profiles/{prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "oauth"},
    ).json()
    exp_state = parse_qs(urlparse(exp_start["authorization_url"]).query)["state"][0]
    row = memory_repos["publishing"].get_oauth_state_by_hash(hash_token(exp_state))
    assert row is not None
    row.expires_at = utc_now_naive() - timedelta(minutes=1)
    expired_cb = client.post(
        f"/api/v1/social-profiles/{prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": exp_state, "code": "late-code"},
    )
    assert expired_cb.status_code == 422

    # Disconnect clears secrets cleanly while preserving profile
    disc = client.post(
        f"/api/v1/social-profiles/{prof['id']}/disconnect",
        headers={"X-CSRF-Token": csrf},
        json={"clear_credentials": True, "switch_to_manual": False},
    )
    assert disc.status_code == 200
    assert disc.json()["connection_status"] == "disconnected"
    stored_after = memory_repos["social_profiles"].get_by_id(prof["id"])
    assert stored_after is not None and stored_after.encrypted_access_token is None


def test_all_official_platform_adapters_verify_targets_and_refresh(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
) -> None:
    client, csrf = auth_client

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        params = dict(request.url.params)
        # Meta Facebook Pages & Instagram Graph
        if host == "graph.facebook.com":
            if path.endswith("/oauth/access_token"):
                if params.get("grant_type") == "fb_exchange_token":
                    return httpx.Response(
                        200,
                        json={"access_token": "meta_long_token", "expires_in": 5184000},
                    )
                return httpx.Response(200, json={"access_token": "meta_short_token"})
            if path.endswith("/me/accounts"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "page_101",
                                "name": "Bygame Official Page",
                                "category": "Gaming",
                                "link": "https://www.facebook.com/page_101",
                                "access_token": "page_101_token",
                                "instagram_business_account": {
                                    "id": "ig_901",
                                    "username": "bygame.ig",
                                    "name": "Bygame IG",
                                },
                            },
                            {
                                "id": "page_202",
                                "name": "Bygame Promo Page",
                                "category": "Media",
                                "link": "https://www.facebook.com/page_202",
                                "access_token": "page_202_token",
                            },
                        ]
                    },
                )
            if path.endswith("/debug_token"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "is_valid": True,
                            "scopes": ["pages_manage_posts", "pages_read_engagement"],
                            "expires_at": 0,
                        }
                    },
                )
            if path.endswith("/me"):
                # Personal user node lacks Page category
                return httpx.Response(200, json={"id": "user_55", "name": "Personal User"})
            if path.endswith("/page_202"):
                return httpx.Response(
                    200,
                    json={
                        "id": "page_202",
                        "name": "Bygame Promo Page",
                        "category": "Media",
                        "link": "https://www.facebook.com/page_202",
                    },
                )
            if path.endswith("/ig_personal"):
                return httpx.Response(
                    200,
                    json={"id": "ig_personal", "username": "me", "account_type": "PERSONAL"},
                )
            if path.endswith("/ig_901"):
                return httpx.Response(
                    200,
                    json={
                        "id": "ig_901",
                        "username": "bygame.ig",
                        "name": "Bygame IG",
                        "account_type": "BUSINESS",
                    },
                )
            if path.endswith("/content_publishing_limit"):
                return httpx.Response(
                    200,
                    json={"data": [{"quota_usage": 2, "config": {"quota_total": 50}}]},
                )

        # Threads
        if host == "graph.threads.net":
            if path == "/oauth/access_token":
                return httpx.Response(200, json={"access_token": "th_short", "user_id": "th_1"})
            if path == "/access_token":
                return httpx.Response(
                    200, json={"access_token": "th_long", "expires_in": 5184000}
                )
            if path == "/refresh_access_token":
                return httpx.Response(
                    200, json={"access_token": "th_long_refreshed", "expires_in": 5184000}
                )
            if path.endswith("/me"):
                return httpx.Response(
                    200, json={"id": "th_1", "username": "bygame.threads", "name": "Bygame"}
                )
            if path.endswith("/threads_publishing_limit"):
                return httpx.Response(200, json={"data": [{"quota_usage": 1}]})

        # Google Business Profile
        if host == "oauth2.googleapis.com" and path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "gbp_access_1",
                    "refresh_token": "gbp_refresh_1",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/business.manage",
                },
            )
        if host == "mybusinessaccountmanagement.googleapis.com" and path == "/v1/accounts":
            if "Bearer empty_qpm" in request.headers.get("authorization", ""):
                return httpx.Response(200, json={"accounts": []})
            return httpx.Response(
                200, json={"accounts": [{"name": "accounts/123", "accountName": "Bygame Group"}]}
            )
        if host == "mybusinessbusinessinformation.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "locations": [
                        {
                            "name": "accounts/123/locations/456",
                            "title": "Bygame Makati Hub",
                            "websiteUri": "https://bygame.ph",
                        }
                    ]
                },
            )

        # LinkedIn
        if host == "www.linkedin.com" and path == "/oauth/v2/accessToken":
            return httpx.Response(
                200,
                json={
                    "access_token": "li_access_1",
                    "refresh_token": "li_refresh_1",
                    "expires_in": 5184000,
                    "scope": "openid profile w_member_social",
                },
            )
        if host == "api.linkedin.com" and path == "/v2/userinfo":
            return httpx.Response(200, json={"sub": "li_person_42", "name": "Bygame Editor"})
        if host == "api.linkedin.com" and path == "/rest/organizationAcls":
            return httpx.Response(
                200, json={"elements": [{"organization": "urn:li:organization:8800"}]}
            )

        # Pinterest
        if host == "api.pinterest.com":
            if path == "/v5/oauth/token":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "pin_access_1",
                        "refresh_token": "pin_refresh_1",
                        "expires_in": 2592000,
                        "scope": "boards:read pins:read pins:write user_accounts:read",
                    },
                )
            if path == "/v5/user_account":
                return httpx.Response(
                    200, json={"username": "bygamepins", "account_type": "BUSINESS"}
                )
            if path == "/v5/boards":
                return httpx.Response(
                    200, json={"items": [{"id": "board_77", "name": "Featured Slots"}]}
                )

        raise AssertionError(f"Unhandled mock endpoint: {request.method} {request.url}")

    app.dependency_overrides[get_publisher_registry] = lambda: PublisherAdapterRegistry(
        settings=test_settings, transport=httpx.MockTransport(handler)
    )
    site = _create_website(client, csrf)

    # 1. Facebook Pages OAuth + target selection + personal profile rejection
    fb_prof = _create_profile(
        client, csrf, site["id"], platform_key="facebook", profile_name="Bygame FB"
    )
    fb_start = client.post(
        f"/api/v1/social-profiles/{fb_prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "oauth", "app_id": "fb_app", "app_secret": "fb_sec"},
    ).json()
    fb_state = parse_qs(urlparse(fb_start["authorization_url"]).query)["state"][0]
    fb_cb = client.post(
        f"/api/v1/social-profiles/{fb_prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": fb_state, "code": "fb-code"},
    ).json()
    assert len(fb_cb["available_targets"]) == 2
    fb_sel = client.post(
        f"/api/v1/social-profiles/{fb_prof['id']}/select-target",
        headers={"X-CSRF-Token": csrf},
        json={"target_resource_id": "page_202"},
    ).json()
    assert fb_sel["target_resource_id"] == "page_202"
    assert fb_sel["eligibility_status"] == "eligible"

    fb_personal = _create_profile(
        client, csrf, site["id"], platform_key="facebook", profile_name="Personal Rejected"
    )
    fb_pers_res = client.post(
        f"/api/v1/social-profiles/{fb_personal['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "credentials", "access_token": "personal_user_tok"},
    ).json()["connection"]
    assert fb_pers_res["connection_status"] == "restricted"
    assert fb_pers_res["last_error_code"] == "FB_PERSONAL_PROFILE_UNSUPPORTED"

    # 2. Instagram Business vs Personal rejection
    ig_prof = _create_profile(
        client, csrf, site["id"], platform_key="instagram", profile_name="Bygame IG"
    )
    ig_ok = client.post(
        f"/api/v1/social-profiles/{ig_prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "credentials",
            "access_token": "ig_tok",
            "external_account_id": "ig_901",
            "target_resource_id": "ig_901",
        },
    ).json()["connection"]
    assert ig_ok["eligibility_status"] == "eligible"

    ig_bad = _create_profile(
        client, csrf, site["id"], platform_key="instagram", profile_name="Personal IG"
    )
    ig_pers = client.post(
        f"/api/v1/social-profiles/{ig_bad['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "credentials",
            "access_token": "ig_tok",
            "external_account_id": "ig_personal",
            "target_resource_id": "ig_personal",
        },
    ).json()["connection"]
    assert ig_pers["connection_status"] == "restricted"
    assert ig_pers["last_error_code"] == "IG_PERSONAL_UNSUPPORTED"

    # 3. Threads OAuth + refresh
    th_prof = _create_profile(
        client, csrf, site["id"], platform_key="threads", profile_name="Bygame Threads"
    )
    th_start = client.post(
        f"/api/v1/social-profiles/{th_prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "oauth", "app_id": "th_app", "app_secret": "th_sec"},
    ).json()
    th_state = parse_qs(urlparse(th_start["authorization_url"]).query)["state"][0]
    th_cb = client.post(
        f"/api/v1/social-profiles/{th_prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": th_state, "code": "th-code"},
    ).json()
    assert th_cb["external_username"] == "bygame.threads"
    th_ref = client.post(
        f"/api/v1/social-profiles/{th_prof['id']}/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert th_ref.status_code == 200
    assert th_ref.json()["last_refreshed_at"] is not None

    # 4. Google Business Profile OAuth + 0 QPM requires_review
    gbp_prof = _create_profile(
        client, csrf, site["id"], platform_key="google_business_profile", profile_name="GBP"
    )
    gbp_start = client.post(
        f"/api/v1/social-profiles/{gbp_prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "oauth", "app_id": "g_id", "app_secret": "g_sec"},
    ).json()
    gbp_state = parse_qs(urlparse(gbp_start["authorization_url"]).query)["state"][0]
    gbp_cb = client.post(
        f"/api/v1/social-profiles/{gbp_prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": gbp_state, "code": "g-code"},
    ).json()
    assert gbp_cb["target_resource_id"] == "accounts/123/locations/456"
    assert gbp_cb["eligibility_status"] == "eligible"

    gbp_zero = _create_profile(
        client, csrf, site["id"], platform_key="google_business_profile", profile_name="GBP 0QPM"
    )
    gbp_zres = client.post(
        f"/api/v1/social-profiles/{gbp_zero['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "credentials", "access_token": "empty_qpm"},
    ).json()["connection"]
    assert gbp_zres["eligibility_status"] == "requires_review"

    # 5. LinkedIn OAuth + target selection
    li_prof = _create_profile(
        client, csrf, site["id"], platform_key="linkedin", profile_name="Bygame LinkedIn"
    )
    li_start = client.post(
        f"/api/v1/social-profiles/{li_prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "oauth", "app_id": "li_id", "app_secret": "li_sec"},
    ).json()
    li_state = parse_qs(urlparse(li_start["authorization_url"]).query)["state"][0]
    li_cb = client.post(
        f"/api/v1/social-profiles/{li_prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": li_state, "code": "li-code"},
    ).json()
    assert li_cb["target_resource_id"] == "urn:li:person:li_person_42"

    # 6. Pinterest PKCE OAuth + board target + sandbox trial note
    pin_prof = _create_profile(
        client, csrf, site["id"], platform_key="pinterest", profile_name="Bygame Pins"
    )
    pin_start = client.post(
        f"/api/v1/social-profiles/{pin_prof['id']}/connect",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "oauth", "app_id": "pin_id", "app_secret": "pin_sec"},
    ).json()
    assert "code_challenge_method=S256" in pin_start["authorization_url"]
    pin_state = parse_qs(urlparse(pin_start["authorization_url"]).query)["state"][0]
    pin_cb = client.post(
        f"/api/v1/social-profiles/{pin_prof['id']}/oauth/complete",
        headers={"X-CSRF-Token": csrf},
        json={"state": pin_state, "code": "pin-code"},
    ).json()
    assert pin_cb["target_resource_id"] == "board_77"
    pin_ver = client.post(
        f"/api/v1/social-profiles/{pin_prof['id']}/verify",
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert "Trial" in (pin_ver["eligibility_notes"] or "")

    # 7. Aggregate connections list endpoint works cleanly
    conns = client.get(f"/api/v1/publishing/connections?website_id={site['id']}")
    assert conns.status_code == 200
    assert len(conns.json()) >= 8
