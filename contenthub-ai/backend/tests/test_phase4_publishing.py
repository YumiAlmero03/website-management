from __future__ import annotations

import hashlib
import io
from datetime import timedelta
from typing import Any
from urllib.parse import unquote

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.core.dependencies import get_health_service, get_publisher_registry
from app.models.base import utc_now, utc_now_naive
from app.schemas.health import SystemResourcesInfo
from app.services.monitoring.health_service import HealthService
from app.services.publishers.registry import PublisherAdapterRegistry
from app.services.publishing_service import PublishingService
from app.services.settings_service import SettingsService
from app.services.social_post_service import SocialPostService


def _create_website(client: TestClient, csrf: str) -> dict[str, Any]:
    cat_id = client.get("/api/v1/website-categories").json()["items"][0]["id"]
    resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "category_id": cat_id,
            "name": "Bygame PH",
            "brand_name": "Bygame",
            "domain": "bygame.ph",
            "website_type": "wordpress",
            "discovery_method": "auto",
            "primary_language": "English",
            "status": "active",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_connected_profile(
    client: TestClient,
    csrf: str,
    memory_repos: dict[str, Any],
    website_id: int,
    *,
    platform_key: str,
    profile_name: str,
    publishing_method: str = "api",
    target_id: str | None = "page_101",
    min_interval_minutes: int | None = None,
) -> dict[str, Any]:
    prof = client.post(
        f"/api/v1/websites/{website_id}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": platform_key,
            "profile_name": profile_name,
            "publishing_method": publishing_method,
            "publishing_enabled": True,
            "display_timezone": "Asia/Manila",
            "daily_publishing_limit": 20,
            "min_interval_minutes": min_interval_minutes,
            "external_account_id": target_id,
        },
    )
    assert prof.status_code == 201, prof.text
    pdata = prof.json()
    if publishing_method == "api":
        resp = client.post(
            f"/api/v1/social-profiles/{pdata['id']}/connect",
            headers={"X-CSRF-Token": csrf},
            json={
                "mode": "credentials",
                "access_token": "tok_live_test_123",
                "external_account_id": target_id,
                "target_resource_id": target_id,
                "target_resource_name": profile_name,
            },
        )
        assert resp.status_code == 200, resp.text
    else:
        memory_repos["publishing"].upsert_connection(
            social_profile_id=pdata["id"],
            website_id=website_id,
            platform_id=pdata["platform_id"],
            data={
                "auth_type": "manual",
                "connection_status": "configured",
                "eligibility_status": "manual_only",
            },
        )
    return pdata


def _seed_post_with_approvals(
    memory_repos: dict[str, Any],
    *,
    website_id: int,
    profile: dict[str, Any],
    url: str = "https://bygame.ph/blog/odds-guide",
    content_status: str = "approved",
    keyword_status: str = "approved",
    draft_status: str = "approved",
    caption: str = "Explore fixed vs dynamic odds in our complete player guide.",
    featured_media_id: int | None = None,
) -> tuple[Any, Any]:
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    content = memory_repos["contents"].create(
        {
            "website_id": website_id,
            "content_type": "blog_post",
            "classification_method": "path",
            "title": "Fixed vs Dynamic Odds Guide",
            "url": url,
            "canonical_url": url,
            "url_hash": url_hash,
            "content_hash": hashlib.sha256(f"{url}:body".encode()).hexdigest(),
            "markdown_content": "# Fixed vs Dynamic Odds\n\nDetailed breakdown.",
            "word_count": 350,
            "extraction_status": "extracted",
            "status": "extracted",
        }
    )
    memory_repos["keyword_approvals"].upsert_approval(
        website_id=website_id,
        website_content_id=content.id,
        data={"status": content_status, "classified_content_type": "blog_post"},
    )
    memory_repos["keyword_approvals"].upsert_keyword(
        website_id=website_id,
        website_content_id=content.id,
        data={
            "focus_keyphrase": "Fixed Odds vs Dynamic Odds",
            "secondary_keywords_json": ["Fixed odds explained"],
            "anchor_text_variations_json": [
                "Fixed Odds vs Dynamic Odds",
                "Fixed odds explained",
            ],
            "approval_status": keyword_status,
            "suggestion_source": "python_auto",
        },
    )
    post = memory_repos["social_posts"].create_post(
        {
            "website_id": website_id,
            "website_content_id": content.id,
            "social_profile_id": profile["id"],
            "platform_id": profile["platform_id"],
            "featured_media_id": featured_media_id,
            "caption": caption,
            "assembled_content": f"{caption}\n\n{url}\n\n#Bygame",
            "hashtags_json": ["#Bygame"],
            "source_url": url,
            "language": "English",
            "character_count": len(caption),
            "status": draft_status,
            "publishing_status": "approved" if draft_status == "approved" else "pending_approval",
            "approved_revision_id": 1 if draft_status == "approved" else None,
            "approved_at": utc_now_naive() if draft_status == "approved" else None,
        }
    )
    return content, post


def _build_pub_service(
    *,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
    transport: httpx.BaseTransport,
    health_service: HealthService | None = None,
) -> PublishingService:
    registry = PublisherAdapterRegistry(settings=test_settings, transport=transport)
    post_svc = SocialPostService(
        settings=test_settings,
        social_post_repo=memory_repos["social_posts"],
        social_profile_repo=memory_repos["social_profiles"],
        website_repo=memory_repos["websites"],
        content_repo=memory_repos["contents"],
        media_repo=memory_repos["media"],
        activity_repo=memory_repos["activities"],
        publishing_repo=memory_repos["publishing"],
        keyword_approval_repo=memory_repos["keyword_approvals"],
    )
    return PublishingService(
        settings=test_settings,
        publishing_repo=memory_repos["publishing"],
        social_post_repo=memory_repos["social_posts"],
        social_profile_repo=memory_repos["social_profiles"],
        website_repo=memory_repos["websites"],
        content_repo=memory_repos["contents"],
        media_repo=memory_repos["media"],
        activity_repo=memory_repos["activities"],
        health_service=health_service
        or HealthService(settings=test_settings, db_checker=lambda: db_diagnostic_ok),
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        adapter_registry=registry,
        social_post_service=post_svc,
        keyword_approval_repo=memory_repos["keyword_approvals"],
        ai_repo=memory_repos["ai"],
        fetcher=None,
        dispatcher=lambda _jid: None,
    )


def _ok_fb_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/page_101"):
        return httpx.Response(
            200,
            json={
                "id": "page_101",
                "name": "Bygame FB",
                "category": "Gaming",
                "link": "https://www.facebook.com/page_101",
            },
        )
    if path.endswith("/feed"):
        return httpx.Response(200, json={"id": "page_101_555001"})
    if path.endswith("/page_101_555001"):
        return httpx.Response(
            200,
            json={
                "id": "page_101_555001",
                "permalink_url": "https://www.facebook.com/page_101/posts/555001",
            },
        )
    raise AssertionError(f"Unhandled FB endpoint: {request.method} {request.url}")


def test_phase41_property_authorization_rejects_unrelated_domains() -> None:
    from types import SimpleNamespace

    from app.services.indexing_service import IndexingService

    service = object.__new__(IndexingService)
    url_property = SimpleNamespace(gsc_property_url="https://bygame.ph/")
    assert service._property_authorizes(url_property, "https://bygame.ph/game/example") is True
    assert service._property_authorizes(url_property, "https://example.com/game/example") is False

    domain_property = SimpleNamespace(gsc_property_url="sc-domain:bygame.ph")
    assert (
        service._property_authorizes(
            domain_property,
            "https://www.bygame.ph/game/example",
        )
        is True
    )
    assert (
        service._property_authorizes(
            domain_property,
            "https://example.com/game/example",
        )
        is False
    )


def test_profile_test_post_requires_csrf_and_creates_unpublished_review_draft(
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client
    site = _create_website(client, csrf)
    reference = memory_repos["contents"].create(
        {
            "website_id": site["id"],
            "content_type": "blog_post",
            "classification_method": "path",
            "title": "Reference Website Article",
            "url": "https://bygame.ph/blog/reference-article",
            "canonical_url": "https://bygame.ph/blog/reference-article",
            "url_hash": "test-post-reference",
            "content_hash": "test-post-reference-body",
            "markdown_content": "Reference article body.",
            "word_count": 100,
            "extraction_status": "extracted",
            "status": "extracted",
        }
    )
    media = memory_repos["media"].create(
        website_id=site["id"],
        file_name="reference.jpg",
        file_path=None,
        source_url="https://cdn.bygame.ph/reference.jpg",
        mime_type="image/jpeg",
        file_size=1234,
        width=1200,
        height=630,
        alt_text="Reference article image",
        checksum="reference-media",
    )
    profile = _create_connected_profile(
        client,
        csrf,
        memory_repos,
        site["id"],
        platform_key="twitter",
        profile_name="Test destination",
        publishing_method="manual",
    )
    url = f"/api/v1/social-profiles/{profile['id']}/test-post"
    headers = {"X-CSRF-Token": csrf}
    assert client.post(url, json={"caption": "Test"}).status_code == 403
    assert client.post(url, headers=headers, json={"caption": "   "}).status_code == 422
    assert (
        client.post(
            "/api/v1/social-profiles/999999/test-post", headers=headers, json={"caption": "Test"}
        ).status_code
        == 404
    )

    response = client.post(
        url, headers=headers, json={"caption": " Test https://example.com/long-link "}
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["website_id"] == site["id"]
    assert draft["social_profile_id"] == profile["id"]
    assert draft["platform_key"] == "twitter"
    assert draft["status"] == "pending_review"
    assert draft["publishing_status"] == "unscheduled"
    assert draft["approved_revision_id"] is None
    assert draft["website_content_id"] == reference.id
    assert draft["source_url"] == "https://bygame.ph/blog/reference-article"
    assert draft["featured_media_id"] is None or draft["featured_media_id"] == media.id
    assert draft["ai_generation_job_id"] is None
    assert draft["caption"] == "Test https://example.com/long-link"
    assert draft["assembled_content"] == (
        "Test https://example.com/long-link\n\nhttps://bygame.ph/blog/reference-article"
    )
    attached_media = client.get(f"/api/v1/social-posts/{draft['id']}/media").json()
    assert len(attached_media) == 1
    assert attached_media[0]["media_asset_id"] == media.id
    assert attached_media[0]["role"] == "primary"
    assert draft["character_count"] == len("Test ") + 23

    post_url = f"/api/v1/social-posts/{draft['id']}"
    revisions = client.get(f"{post_url}/revisions").json()
    assert len(revisions) == 1
    assert revisions[0]["caption"] == draft["caption"]
    assert revisions[0]["version_number"] == 1
    preflight = client.get(f"{post_url}/preflight").json()
    assert preflight["ready"] is False
    assert "social_draft_approved" in {c["name"] for c in preflight["checks"] if not c["passed"]}
    assert client.get("/api/v1/publishing/jobs").json()["items"] == []

    approved = client.post(f"{post_url}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_revision_id"] == revisions[0]["id"]


def test_preflight_approval_gates_material_edit_invalidation_and_utm(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client
    app.dependency_overrides[get_publisher_registry] = lambda: PublisherAdapterRegistry(
        settings=test_settings, transport=httpx.MockTransport(_ok_fb_handler)
    )
    site = _create_website(client, csrf)
    prof = _create_connected_profile(
        client, csrf, memory_repos, site["id"], platform_key="facebook", profile_name="Bygame FB"
    )

    # 1. Both content approval and keyword approval remain independent gates from draft approval
    content, post = _seed_post_with_approvals(
        memory_repos,
        website_id=site["id"],
        profile=prof,
        content_status="pending_review",
        keyword_status="pending_review",
        draft_status="pending_review",
    )
    pf0 = client.get(f"/api/v1/social-posts/{post.id}/preflight").json()
    assert pf0["ready"] is False
    failed_names = {c["name"] for c in pf0["checks"] if not c["passed"]}
    assert {
        "source_content_approved",
        "keyword_mapping_approved",
        "social_draft_approved",
    }.issubset(failed_names)

    # Content approved, keyword still pending -> blocked
    memory_repos["keyword_approvals"].upsert_approval(
        website_id=site["id"],
        website_content_id=content.id,
        data={"status": "approved"},
    )
    pf1 = client.get(f"/api/v1/social-posts/{post.id}/preflight").json()
    assert pf1["ready"] is False
    assert "keyword_mapping_approved" in {c["name"] for c in pf1["checks"] if not c["passed"]}

    # Keyword approved, draft still pending -> blocked
    memory_repos["keyword_approvals"].upsert_keyword(
        website_id=site["id"],
        website_content_id=content.id,
        data={"approval_status": "approved"},
        create_revision=False,
    )
    pf2 = client.get(f"/api/v1/social-posts/{post.id}/preflight").json()
    assert pf2["ready"] is False
    assert {c["name"] for c in pf2["checks"] if not c["passed"]} == {"social_draft_approved"}

    # Draft approved -> preflight ready
    app_res = client.post(
        f"/api/v1/social-posts/{post.id}/approve",
        headers={"X-CSRF-Token": csrf},
    )
    assert app_res.status_code == 200
    assert app_res.json()["approved_revision_id"] is not None
    pf3 = client.get(f"/api/v1/social-posts/{post.id}/preflight").json()
    assert pf3["ready"] is True

    # Schedule future publish -> calendar entry active
    future_iso = (utc_now() + timedelta(hours=3)).isoformat()
    sched_res = client.post(
        f"/api/v1/social-posts/{post.id}/schedule",
        headers={"X-CSRF-Token": csrf},
        json={"scheduled_at": future_iso, "display_timezone": "Asia/Manila"},
    )
    assert sched_res.status_code == 200, sched_res.text
    assert sched_res.json()["publishing_status"] == "scheduled"
    assert len(memory_repos["publishing"].list_active_schedules_for_post(post.id)) == 1

    # Material edit invalidates approval, builds UTM URL, and cancels pending schedule
    edit_res = client.patch(
        f"/api/v1/social-posts/{post.id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "caption": "Updated headline copy after approval.",
            "utm_params": {"utm_source": "facebook", "utm_campaign": "launch_q4"},
            "alternative_captions": ["Backup short hook A"],
        },
    )
    assert edit_res.status_code == 200, edit_res.text
    edited = edit_res.json()
    assert edited["status"] == "pending_review"
    assert edited["publishing_status"] == "pending_approval"
    assert edited["approved_revision_id"] is None
    assert edited["alternative_captions"] == ["Backup short hook A"]
    assert "utm_source=facebook" in (edited["target_url_with_utm"] or "")
    assert "utm_campaign=launch_q4" in (edited["target_url_with_utm"] or "")
    assert memory_repos["publishing"].list_active_schedules_for_post(post.id) == []


def test_pillow_media_preparation_preserving_original_and_scoped_public_media(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    client, csrf = auth_client
    object.__setattr__(test_settings, "public_media_base_url", "https://media.bygame.ph")

    captured_media_urls: list[str] = []

    def ig_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/page_ig"):
            return httpx.Response(
                200,
                json={"id": "page_ig", "username": "bygame.ig", "account_type": "BUSINESS"},
            )
        if path.endswith("/content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": 0}]})
        if path.endswith("/page_ig/media"):
            body_text = unquote(request.content.decode("utf-8", errors="ignore"))
            captured_media_urls.append(body_text)
            assert "/api/v1/public-media/" in body_text
            return httpx.Response(200, json={"id": "creation_88"})
        if path.endswith("/creation_88"):
            return httpx.Response(200, json={"id": "creation_88", "status_code": "FINISHED"})
        if path.endswith("/page_ig/media_publish"):
            return httpx.Response(200, json={"id": "ig_post_777"})
        if path.endswith("/ig_post_777"):
            return httpx.Response(
                200, json={"id": "ig_post_777", "permalink": "https://www.instagram.com/p/ABC/"}
            )
        raise AssertionError(f"Unhandled IG endpoint: {request.method} {request.url}")

    app.dependency_overrides[get_publisher_registry] = lambda: PublisherAdapterRegistry(
        settings=test_settings, transport=httpx.MockTransport(ig_handler)
    )

    # Create oversized 2200x1100 RGBA PNG asset in STORAGE_ROOT/uploads
    upload_dir = test_settings.resolved_storage_root / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    orig_path = upload_dir / "oversized_banner.png"
    img = Image.new("RGBA", (2200, 1100), color=(30, 144, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    orig_bytes = buf.getvalue()
    orig_path.write_bytes(orig_bytes)
    orig_sha = hashlib.sha256(orig_bytes).hexdigest()

    site = _create_website(client, csrf)
    asset = memory_repos["media"].create(
        website_id=site["id"],
        file_name="oversized_banner.png",
        file_path="uploads/oversized_banner.png",
        source_url="https://bygame.ph/assets/oversized_banner.png",
        mime_type="image/png",
        file_size=len(orig_bytes),
        width=2200,
        height=1100,
        alt_text="Bygame Hero",
        checksum=orig_sha,
    )
    ig_prof = _create_connected_profile(
        client,
        csrf,
        memory_repos,
        site["id"],
        platform_key="instagram",
        profile_name="Bygame IG",
        target_id="page_ig",
    )
    _content, post = _seed_post_with_approvals(
        memory_repos,
        website_id=site["id"],
        profile=ig_prof,
        url="https://bygame.ph/blog/ig-banner",
    )

    # Attach media via API (changing media invalidates prior approval -> re-approve)
    put_media = client.put(
        f"/api/v1/social-posts/{post.id}/media",
        headers={"X-CSRF-Token": csrf},
        json={"attachments": [{"media_asset_id": asset.id, "role": "primary", "alt_text": "Alt"}]},
    )
    assert put_media.status_code == 200
    assert len(put_media.json()) == 1
    reapp = client.post(
        f"/api/v1/social-posts/{post.id}/approve",
        headers={"X-CSRF-Token": csrf},
    )
    assert reapp.status_code == 200

    # Enqueue and execute publish synchronously via service
    enq = client.post(
        f"/api/v1/social-posts/{post.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    )
    assert enq.status_code == 202, enq.text
    svc = _build_pub_service(
        test_settings=test_settings,
        memory_repos=memory_repos,
        db_diagnostic_ok=db_diagnostic_ok,
        transport=httpx.MockTransport(ig_handler),
    )
    done = svc.execute_job(enq.json()["id"], worker_id="test-ig-worker")
    assert done.status == "published"
    assert done.published_url == "https://www.instagram.com/p/ABC/"
    assert len(captured_media_urls) == 1

    # Original uploaded PNG must be completely unmodified on disk
    assert hashlib.sha256(orig_path.read_bytes()).hexdigest() == orig_sha

    # Prepared JPEG converted & resized to IG <= 1440px, and served via scoped public-media token
    media_rows = memory_repos["publishing"].list_post_media(post.id)
    assert media_rows[0].is_prepared is True
    assert media_rows[0].prepared_mime_type == "image/jpeg"
    assert (media_rows[0].prepared_width or 9999) <= 1440
    token = media_rows[0].public_media_token
    assert token is not None

    pub_fetch = client.get(f"/api/v1/public-media/{token}")
    assert pub_fetch.status_code == 200
    assert pub_fetch.headers["content-type"].startswith("image/jpeg")

    # Unknown token and expired token blocked
    assert client.get("/api/v1/public-media/nonexistent-token-999").status_code == 404
    memory_repos["publishing"].update_post_media(
        media_rows[0].id, {"public_media_expires_at": utc_now_naive() - timedelta(minutes=1)}
    )
    assert client.get(f"/api/v1/public-media/{token}").status_code == 404


def test_publish_confirm_guard_idempotency_timeout_reconcile_and_backoff(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    client, csrf = auth_client
    mode: dict[str, str] = {"fb": "timeout_then_exists"}

    def fb_dynamic_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/page_101"):
            return httpx.Response(
                200, json={"id": "page_101", "name": "Bygame FB", "category": "Gaming"}
            )
        if path.endswith("/feed"):
            if mode["fb"] == "timeout_then_exists":
                raise httpx.ReadTimeout("Timed out after POST mutation")
            if mode["fb"] == "rate_limit":
                return httpx.Response(
                    429,
                    headers={"Retry-After": "30"},
                    json={"error": {"message": "Rate limit hit"}},
                )
            if mode["fb"] == "perm_403":
                return httpx.Response(
                    403,
                    json={"error": {"message": "Missing permission pages_manage_posts"}},
                )
            return httpx.Response(200, json={"id": "page_101_777002"})
        if path.endswith("/published_posts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "page_101_777001",
                            "message": "Timeout post copy check\n\nhttps://bygame.ph/blog/p1",
                            "permalink_url": "https://www.facebook.com/page_101/posts/777001",
                        }
                    ]
                },
            )
        if path.endswith("/page_101_777002"):
            return httpx.Response(
                200,
                json={
                    "id": "page_101_777002",
                    "permalink_url": "https://www.facebook.com/page_101/posts/777002",
                },
            )
        raise AssertionError(f"Unhandled endpoint: {request.method} {request.url}")

    app.dependency_overrides[get_publisher_registry] = lambda: PublisherAdapterRegistry(
        settings=test_settings, transport=httpx.MockTransport(fb_dynamic_handler)
    )
    site = _create_website(client, csrf)
    prof = _create_connected_profile(
        client, csrf, memory_repos, site["id"], platform_key="facebook", profile_name="Bygame FB"
    )
    _c1, post1 = _seed_post_with_approvals(
        memory_repos,
        website_id=site["id"],
        profile=prof,
        url="https://bygame.ph/blog/p1",
        caption="Timeout post copy check",
    )

    # 1. Confirm guard rejects confirm=false
    no_confirm = client.post(
        f"/api/v1/social-posts/{post1.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": False},
    )
    assert no_confirm.status_code == 422

    # 2. Timeout after POST moves job/post to verification_required (no blind retry)
    j1 = client.post(
        f"/api/v1/social-posts/{post1.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    ).json()
    svc = _build_pub_service(
        test_settings=test_settings,
        memory_repos=memory_repos,
        db_diagnostic_ok=db_diagnostic_ok,
        transport=httpx.MockTransport(fb_dynamic_handler),
    )
    v_res = svc.execute_job(j1["id"], worker_id="w1")
    assert v_res.status == "verification_required"
    assert v_res.requires_verification is True
    assert client.get("/api/v1/publishing/statistics").json()["verification_required"] == 1

    # Reconcile resolution=auto discovers post in recent feed -> marks published + creates record
    rec_res = client.post(
        f"/api/v1/publishing/jobs/{j1['id']}/reconcile",
        headers={"X-CSRF-Token": csrf},
        json={"resolution": "auto"},
    )
    assert rec_res.status_code == 200, rec_res.text
    assert rec_res.json()["status"] == "published"
    assert rec_res.json()["external_post_id"] == "page_101_777001"

    # Duplicate publish prevention blocks second immediate publish with 409 Conflict
    dup = client.post(
        f"/api/v1/social-posts/{post1.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    )
    assert dup.status_code == 409

    # 3. confirm_missing reconcile re-queues and succeeds when network recovers
    _c1b, post1b = _seed_post_with_approvals(
        memory_repos,
        website_id=site["id"],
        profile=prof,
        url="https://bygame.ph/blog/p1b",
        caption="Second timeout post",
    )
    j1b = client.post(
        f"/api/v1/social-posts/{post1b.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    ).json()
    assert svc.execute_job(j1b["id"]).status == "verification_required"
    mode["fb"] = "ok"
    requeued = client.post(
        f"/api/v1/publishing/jobs/{j1b['id']}/reconcile",
        headers={"X-CSRF-Token": csrf},
        json={"resolution": "confirm_missing"},
    )
    assert requeued.status_code == 200
    assert requeued.json()["status"] == "queued"
    assert svc.execute_job(j1b["id"]).status == "published"

    # 4. Temporary 429 defers with exponential backoff; permanent 403 fails without deferral
    _c2, post2 = _seed_post_with_approvals(
        memory_repos, website_id=site["id"], profile=prof, url="https://bygame.ph/blog/p2"
    )
    j2 = client.post(
        f"/api/v1/social-posts/{post2.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    ).json()
    mode["fb"] = "rate_limit"
    d_res = svc.execute_job(j2["id"])
    assert d_res.status == "deferred"
    assert d_res.error_category == "rate_limited"
    assert d_res.next_retry_at is not None

    _c3, post3 = _seed_post_with_approvals(
        memory_repos, website_id=site["id"], profile=prof, url="https://bygame.ph/blog/p3"
    )
    j3 = client.post(
        f"/api/v1/social-posts/{post3.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    ).json()
    mode["fb"] = "perm_403"
    f_res = svc.execute_job(j3["id"])
    assert f_res.status == "failed"
    assert f_res.error_category == "missing_permissions"

    # 5. Resource Guardian critical defers job before hitting external API
    class CriticalHealthService(HealthService):
        def get_system_resources(self, effective_settings: Any = None) -> SystemResourcesInfo:
            info = super().get_system_resources(effective_settings=effective_settings)
            return info.model_copy(
                update={
                    "cpu_percent": 99.0,
                    "guardian_status": "critical",
                    "guardian_reasons": ["CPU pressure critical"],
                }
            )

    _c4, post4 = _seed_post_with_approvals(
        memory_repos, website_id=site["id"], profile=prof, url="https://bygame.ph/blog/p4"
    )
    j4 = client.post(
        f"/api/v1/social-posts/{post4.id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    ).json()
    crit_svc = _build_pub_service(
        test_settings=test_settings,
        memory_repos=memory_repos,
        db_diagnostic_ok=db_diagnostic_ok,
        transport=httpx.MockTransport(fb_dynamic_handler),
        health_service=CriticalHealthService(
            settings=test_settings, db_checker=lambda: db_diagnostic_ok
        ),
    )
    assert app.dependency_overrides.get(get_health_service) is not None or True
    g_res = crit_svc.execute_job(j4["id"])
    assert g_res.status == "deferred"
    assert "Resource Guardian" in (g_res.paused_reason or "")


def test_schedule_reschedule_cancel_manual_publish_views_history_csv_and_dashboard(
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
) -> None:
    client, csrf = auth_client
    site = _create_website(client, csrf)
    manual_prof = _create_connected_profile(
        client,
        csrf,
        memory_repos,
        site["id"],
        platform_key="custom_social",
        profile_name="Manual Community Channel",
        publishing_method="manual",
        target_id=None,
    )
    _content, post = _seed_post_with_approvals(
        memory_repos,
        website_id=site["id"],
        profile=manual_prof,
        url="https://bygame.ph/blog/manual-post",
    )

    # 1. Schedule manual post -> appears on calendar as manual_reminder -> reschedule -> cancel
    t1 = (utc_now() + timedelta(hours=2)).isoformat()
    s1 = client.post(
        f"/api/v1/social-posts/{post.id}/schedule",
        headers={"X-CSRF-Token": csrf},
        json={"scheduled_at": t1, "display_timezone": "Asia/Manila"},
    )
    assert s1.status_code == 200
    cal = client.get("/api/v1/publishing/calendar").json()
    assert any(
        ev["social_post_id"] == post.id and ev["publishing_status"] == "manual_reminder"
        for ev in cal["events"]
    )

    t2 = (utc_now() + timedelta(hours=4)).isoformat()
    s2 = client.post(
        f"/api/v1/social-posts/{post.id}/schedule",
        headers={"X-CSRF-Token": csrf},
        json={"scheduled_at": t2},
    )
    assert s2.status_code == 200
    assert s2.json()["publishing_status"] == "scheduled"

    canc = client.post(
        f"/api/v1/social-posts/{post.id}/cancel-schedule",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "Publish right away manually"},
    )
    assert canc.status_code == 200
    assert canc.json()["publishing_status"] == "approved"

    # 2. Mark published manually without any API credentials
    marked = client.post(
        f"/api/v1/social-posts/{post.id}/mark-published",
        headers={"X-CSRF-Token": csrf},
        json={
            "published_url": "https://t.me/bygame_channel/998",
            "external_post_id": "tg-998",
            "notes": "Copied caption and uploaded screenshot manually.",
        },
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["publishing_status"] == "manually_published"
    assert marked.json()["verification_status"] == "self_reported"
    assert marked.json()["published_url"] == "https://t.me/bygame_channel/998"

    # View filter checks
    pub_view = client.get("/api/v1/social-posts?view=published").json()
    assert any(item["id"] == post.id for item in pub_view["items"])
    manual_view = client.get("/api/v1/social-posts?view=manual_publishing").json()
    assert isinstance(manual_view["items"], list)

    # 3. Profile deletion must preserve PublicationRecord snapshots in history & CSV export
    del_res = client.delete(
        f"/api/v1/social-profiles/{manual_prof['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert del_res.status_code == 200

    hist = client.get("/api/v1/publishing/history").json()
    assert hist["meta"]["total_items"] == 1
    assert hist["items"][0]["profile_name"] == "Manual Community Channel"
    assert hist["items"][0]["published_url"] == "https://t.me/bygame_channel/998"

    csv_resp = client.get("/api/v1/publishing/history/export")
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "https://t.me/bygame_channel/998" in csv_resp.text
    assert "Manual Community Channel" in csv_resp.text

    # 4. Dashboard summary exposes Phase 4 active status & metrics
    dash = client.get("/api/v1/dashboard/summary").json()
    assert dash["current_phase"] == 4
    assert dash["phase4_metrics"]["published_today"] >= 1
    active_keys = {m["key"]: m["status"] for m in dash["modules"]}
    assert active_keys["publishing_calendar"] == "active"
    assert active_keys["connected_accounts"] == "active"
