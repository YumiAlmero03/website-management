from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.dependencies import (
    get_activity_log_repo,
    get_ai_provider_client,
    get_ai_repo,
    get_category_repo,
    get_content_repo,
    get_keyword_approval_repo,
    get_media_repo,
    get_scan_log_repo,
    get_social_post_repo,
    get_social_profile_repo,
    get_website_repo,
    get_website_source_repo,
)
from app.core.security import encrypt_secret
from app.database import DatabaseDiagnostic
from app.models.base import utc_now_naive
from app.services.ai.generation_service import AiGenerationService
from app.services.content.keyword_suggester import suggest_keywords_for_content
from app.services.content_approval_service import ContentApprovalService
from app.services.monitoring.health_service import HealthService
from app.services.scan_executor import ScanExecutorService
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from tests.conftest import public_dns_resolver


def _create_website(client: TestClient, csrf: str, *, name: str, domain: str) -> dict[str, Any]:
    cats = client.get("/api/v1/website-categories").json()["items"]
    cat_id = cats[0]["id"]
    res = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "brand_name": name.split()[0],
            "domain": domain,
            "category_id": cat_id,
            "website_type": "wordpress",
            "discovery_method": "auto",
            "primary_language": "Taglish",
            "target_country": "Philippines",
            "auto_generate": True,
            "auto_generate_require_published_at": False,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _configure_provider_and_profile(
    app: FastAPI,
    client: TestClient,
    csrf: str,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    *,
    website_id: int,
) -> dict[str, Any]:
    ai_repo = app.dependency_overrides[get_ai_repo]()
    existing_provider = ai_repo.get_default_provider()
    if existing_provider is None:
        key_cipher = encrypt_secret(
            "AIzaFakeTestKey999888777666555", test_settings.app_encryption_key
        )
        ai_repo.create_provider(
            {
                "name": "Gemini Free-First Default",
                "provider_type": "gemini",
                "encrypted_api_key": key_cipher,
                "selected_model": "gemini-3.5-flash-lite",
                "default_temperature": 0.4,
                "max_output_tokens": 1200,
                "request_timeout_seconds": 30,
                "max_retry_attempts": 1,
                "daily_request_limit": 200,
                "daily_token_limit": 500000,
                "per_minute_request_limit": 20,
                "generation_enabled": True,
                "response_caching_enabled": True,
                "token_optimization_enabled": True,
                "allow_paid_fallback": False,
                "is_default": True,
                "is_active": True,
                "last_test_status": "valid",
            }
        )
    # Seed default prompt template if missing
    if not ai_repo.list_prompts(task_type="multi_platform_social"):
        from app.services.ai.defaults import DEFAULT_PROMPT_TEMPLATES

        for tpl in DEFAULT_PROMPT_TEMPLATES:
            ai_repo.create_prompt(
                {
                    "template_key": tpl["template_key"],
                    "scope_key": "global",
                    "name": tpl["name"],
                    "task_type": tpl["task_type"],
                    "platform_key": tpl["platform_key"],
                    "system_instructions": tpl["system_instructions"],
                    "user_prompt_template": tpl["user_prompt_template"],
                    "available_variables_json": list(tpl["available_variables_json"]),
                    "response_schema_name": tpl["response_schema_name"],
                    "version": tpl["version"],
                    "is_active": tpl["is_active"],
                    "is_system_default": tpl["is_system_default"],
                },
                user_id=None,
            )

    prof_res = client.post(
        f"/api/v1/websites/{website_id}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": "facebook",
            "profile_name": f"Site {website_id} Facebook",
            "is_active": True,
            "generation_enabled": True,
            "automatic_generation_enabled": True,
        },
    )
    assert prof_res.status_code == 201, prof_res.text
    return prof_res.json()


def _build_services_for_scan(
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: DatabaseDiagnostic,
    *,
    routes: dict[str, httpx.Response],
) -> tuple[ScanExecutorService, AiGenerationService]:
    website_repo = app.dependency_overrides[get_website_repo]()
    source_repo = app.dependency_overrides[get_website_source_repo]()
    content_repo = app.dependency_overrides[get_content_repo]()
    scan_repo = app.dependency_overrides[get_scan_log_repo]()
    media_repo = app.dependency_overrides[get_media_repo]()
    activity_repo = app.dependency_overrides[get_activity_log_repo]()
    ai_repo = app.dependency_overrides[get_ai_repo]()
    kw_repo = app.dependency_overrides[get_keyword_approval_repo]()
    profile_repo = app.dependency_overrides[get_social_profile_repo]()
    post_repo = app.dependency_overrides[get_social_post_repo]()
    ai_client = app.dependency_overrides[get_ai_provider_client]()
    health_svc = HealthService(settings=test_settings, db_checker=lambda: db_diagnostic_ok)
    settings_svc = SettingsService(
        settings=test_settings,
        settings_repo=memory_repos["settings"],
        activity_repo=activity_repo,
    )

    gen_svc = AiGenerationService(
        settings=test_settings,
        ai_repo=ai_repo,
        website_repo=website_repo,
        category_repo=app.dependency_overrides[get_category_repo](),
        content_repo=content_repo,
        social_profile_repo=profile_repo,
        social_post_repo=post_repo,
        activity_repo=activity_repo,
        health_service=health_svc,
        settings_service=settings_svc,
        provider_client=ai_client,
        dispatcher=lambda jid: memory_repos["dispatched_ai_jobs"].append(jid),
        keyword_approval_repo=kw_repo,
    )
    approval_svc = ContentApprovalService(
        settings=test_settings,
        keyword_approval_repo=kw_repo,
        content_repo=content_repo,
        website_repo=website_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        ai_repo=ai_repo,
        provider_client=ai_client,
        ai_generation_service=gen_svc,
    )

    def _handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url in routes:
            return routes[url]
        alt = url.rstrip("/")
        if alt in routes:
            return routes[alt]
        return httpx.Response(404)

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(_handler),
    )
    executor = ScanExecutorService(
        settings=test_settings,
        website_repo=website_repo,
        source_config_repo=source_repo,
        content_repo=content_repo,
        scan_log_repo=scan_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        health_service=health_svc,
        settings_service=settings_svc,
        fetcher=fetcher,
        dispatcher=lambda _sid: None,
        ai_generation_service=gen_svc,
        approval_service=approval_svc,
    )
    return executor, gen_svc


def test_python_keyword_suggestion_quality_and_alt_distinction(
    app: FastAPI, memory_repos: dict[str, Any]
) -> None:
    content_repo = app.dependency_overrides[get_content_repo]()
    content = content_repo.create(
        {
            "website_id": 1,
            "content_type": "blog_post",
            "classification_method": "path",
            "title": "Fixed Odds vs Dynamic Odds: What's the Difference? | Bygame",
            "url": "https://bygame.ph/blog/fixed-odds-vs-dynamic-odds-whats-the-difference/",
            "canonical_url": "https://bygame.ph/blog/fixed-odds-vs-dynamic-odds-whats-the-difference/",
            "url_hash": "a" * 64,
            "h1_text": "Fixed Odds vs Dynamic Odds: What's the Difference?",
            "meta_description": (
                "Compare how fixed odds work versus dynamic odds in live sports markets."
            ),
            "markdown_content": (
                "# Fixed Odds vs Dynamic Odds: What's the Difference?\n\n"
                "## Fixed Odds Explained\n"
                "Fixed odds lock your payout multiplier when you place a ticket.\n\n"
                "## How Dynamic Odds Work\n"
                "Dynamic odds shift in real time as liquidity and probabilities change.\n"
            ),
            "keywords": ["fixed odds", "dynamic odds", "sports betting comparison"],
            "discovery_sources": ["sitemap"],
            "content_hash": "hash-1",
            "word_count": 40,
            "extraction_status": "extracted",
            "status": "extracted",
        }
    )

    result = suggest_keywords_for_content(
        content=content,
        extracted_headings=[
            "Fixed Odds Explained",
            "How Dynamic Odds Work",
            "Fixed and Dynamic Odds Comparison",
        ],
        extracted_images=[
            {
                "url": "https://bygame.ph/images/odds-comparison-chart.png",
                "alt": "",
                "context": "Article comparison chart",
            }
        ],
    )

    assert "fixed odds" in result.focus_keyphrase.lower()
    assert "dynamic odds" in result.focus_keyphrase.lower()
    assert len(result.secondary_keywords) >= 2
    assert len(result.anchor_text_variations) >= 2
    assert len(result.image_alt_suggestions) == 1
    suggested_alt = result.image_alt_suggestions[0]["suggested_alt"]
    # Image alt text describes visuals cleanly without dumping comma-separated keywords.
    assert (
        "odds comparison chart" in suggested_alt.lower()
        or "illustration" in suggested_alt.lower()
    )
    assert "," not in suggested_alt


def test_full_approval_workflow_inline_editing_preservation_and_ai_gating(
    app: FastAPI,
    auth_client: tuple[TestClient, str],
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: DatabaseDiagnostic,
) -> None:
    client, csrf = auth_client
    site = _create_website(client, csrf, name="Bygame Casino", domain="bygame.ph")
    _configure_provider_and_profile(
        app, client, csrf, test_settings, memory_repos, website_id=site["id"]
    )
    website_repo = app.dependency_overrides[get_website_repo]()
    # Mark baseline completed so next discovered blog post qualifies as newly published.
    website_repo.update(site["id"], {"initial_scan_completed": True})

    robots_txt = "User-agent: *\nAllow: /\n"
    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://bygame.ph/</loc></url>"
        "<url><loc>https://bygame.ph/about</loc></url>"
        "<url><loc>https://bygame.ph/blog/fixed-odds-vs-dynamic-odds/</loc>"
        "<lastmod>2026-11-27T08:00:00Z</lastmod></url>"
        "<url><loc>https://bygame.ph/blog/duplicate-promo/</loc>"
        "<lastmod>2026-11-27T09:00:00Z</lastmod></url>"
        "</urlset>"
    )
    home_html = (
        "<html><head><title>Bygame Philippines</title>"
        "<meta name='description' content='Trusted gaming guide in PH.'/></head>"
        "<body><main><h1>Bygame Official Portal</h1>"
        "<p>Welcome to Bygame guides.</p></main></body></html>"
    )
    about_html = (
        "<html><head><title>About Bygame Team</title></head>"
        "<body><main><h1>About Bygame Editorial Standards</h1>"
        "<p>Independent analysis and transparent rules overview.</p></main></body></html>"
    )
    blog_html = (
        "<html><head>"
        "<title>Fixed Odds vs Dynamic Odds: What's the Difference?</title>"
        "<meta property='og:type' content='article'/>"
        "<meta property='article:published_time' content='2026-11-27T08:00:00Z'/>"
        "</head><body><main><article>"
        "<h1>Fixed Odds vs Dynamic Odds</h1>"
        "<h2>Fixed Odds Explained</h2><p>Locked multiplier once placed.</p>"
        "<h2>How Dynamic Odds Work</h2><p>Live prices adjust with market liquidity.</p>"
        "<img src='https://bygame.ph/uploads/odds-board-diagram.webp' "
        "alt='Live odds board comparison'/>"
        "</article></main></body></html>"
    )
    dup_blog_html = (
        "<html><head>"
        "<title>Unwanted Promotional Spam Post</title>"
        "<meta property='og:type' content='article'/>"
        "<meta property='article:published_time' content='2026-11-27T09:00:00Z'/>"
        "</head><body><main><article>"
        "<h1>Temporary Duplicate Promo</h1><p>Short promotional announcement text.</p>"
        "</article></main></body></html>"
    )

    routes = {
        "https://bygame.ph/robots.txt": httpx.Response(200, text=robots_txt),
        "https://bygame.ph/sitemap.xml": httpx.Response(200, text=sitemap_xml),
        "https://bygame.ph/": httpx.Response(200, text=home_html),
        "https://bygame.ph/about": httpx.Response(200, text=about_html),
        "https://bygame.ph/blog/fixed-odds-vs-dynamic-odds/": httpx.Response(200, text=blog_html),
        "https://bygame.ph/blog/duplicate-promo/": httpx.Response(200, text=dup_blog_html),
    }

    executor, gen_svc = _build_services_for_scan(
        app, test_settings, memory_repos, db_diagnostic_ok, routes=routes
    )
    scan_res = client.post(
        f"/api/v1/websites/{site['id']}/scan",
        headers={"X-CSRF-Token": csrf},
        json={"scan_mode": "full", "trigger_type": "manual"},
    )
    assert scan_res.status_code == 202
    scan_id = scan_res.json()["id"]
    executor.execute_scan(scan_id)

    # 1. Scanning MUST NOT auto-approve or auto-trigger Gemini social generation!
    assert memory_repos["dispatched_ai_jobs"] == []

    # 2. All discovered eligible pages & blog posts enter Pending Review with suggestions
    queue = client.get("/api/v1/content-approvals", params={"website_id": site["id"]}).json()
    assert queue["stats"]["pending_review"] == 4
    assert queue["stats"]["approved"] == 0

    by_url = {item["canonical_url"]: item for item in queue["items"]}
    blog_item = by_url["https://bygame.ph/blog/fixed-odds-vs-dynamic-odds"]
    page_item = by_url["https://bygame.ph/about"]
    rejected_item = by_url["https://bygame.ph/blog/duplicate-promo"]
    home_item = by_url["https://bygame.ph/"]
    assert blog_item["status"] == "pending_review"
    assert blog_item["keyword_mapping"]["focus_keyphrase"]
    assert home_item["meta_description"] == "Trusted gaming guide in PH."
    assert blog_item["published_at"] is not None
    assert blog_item["first_discovered_at"] is not None

    # Automatic generation must stay blocked while content & keywords are still Pending Review
    content_repo = app.dependency_overrides[get_content_repo]()
    site_obj = website_repo.get_by_id(site["id"])
    blog_obj = content_repo.get_by_id(blog_item["content_id"])
    assert site_obj is not None and blog_obj is not None
    assert gen_svc.enqueue_auto_scan_generation(website=site_obj, content=blog_obj) is None

    # 3. Reject unwanted item -> excluded from AI generation & unaffected by unchanged rescan.
    rej_res = client.post(
        f"/api/v1/content-approvals/{rejected_item['content_id']}/reject",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "Not suitable for editorial SEO"},
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"

    blocked_gen = client.post(
        f"/api/v1/contents/{rejected_item['content_id']}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={"trigger_type": "manual"},
    )
    assert blocked_gen.status_code == 422

    # 4. Inline edit focus keyphrase, secondary keywords & anchor text WHILE APPROVING blog post!
    app_blog = client.post(
        f"/api/v1/content-approvals/{blog_item['content_id']}/approve",
        headers={"X-CSRF-Token": csrf},
        json={
            "focus_keyphrase": "Fixed Odds vs Dynamic Odds",
            "secondary_keywords": [
                "Difference between fixed and dynamic odds",
                "Fixed odds explained",
                "How dynamic odds work",
            ],
            "anchor_text_variations": [
                "Fixed Odds vs Dynamic Odds",
                "fixed vs dynamic odds comparison",
            ],
            "review_note": "Approved with tuned focus keyphrase",
            "trigger_auto_generation": True,
        },
    )
    assert app_blog.status_code == 200, app_blog.text
    app_data = app_blog.json()
    assert app_data["item"]["status"] == "approved"
    assert app_data["item"]["keyword_mapping"]["approval_status"] == "approved"
    assert app_data["item"]["keyword_mapping"]["focus_keyphrase"] == "Fixed Odds vs Dynamic Odds"
    assert app_data["auto_generation_job_id"] is not None
    first_job_id = app_data["auto_generation_job_id"]
    assert len(memory_repos["dispatched_ai_jobs"]) == 1

    # Approve /about page without auto-gen (pages do not auto-trigger social drafts).
    app_page = client.post(
        f"/api/v1/content-approvals/{page_item['content_id']}/approve",
        headers={"X-CSRF-Token": csrf},
        json={"focus_keyphrase": "About Bygame Team"},
    )
    assert app_page.status_code == 200
    assert app_page.json()["auto_generation_job_id"] is None

    # Execute queued AI job and verify approved focus + secondary keywords entered Gemini prompt.
    job_res = gen_svc.execute_job(first_job_id)
    assert job_res.status == "completed"
    ai_client = memory_repos["ai_client"]
    last_call = ai_client.calls[-1]
    assert "Fixed Odds vs Dynamic Odds" in last_call["user_prompt"]
    assert "Difference between fixed and dynamic odds" in last_call["user_prompt"]

    # Approve social post manually, then edit keywords -> cache invalidates cleanly.
    posts_before = client.get(
        f"/api/v1/contents/{blog_item['content_id']}/social-posts"
    ).json()
    assert len(posts_before) == 1
    post_id = posts_before[0]["id"]
    app_post_res = client.post(
        f"/api/v1/social-posts/{post_id}/approve", headers={"X-CSRF-Token": csrf}
    )
    assert app_post_res.status_code == 200 and app_post_res.json()["status"] == "approved"

    # Update keywords manually (version bumps to 2); approved social draft remains protected.
    kw_upd = client.patch(
        f"/api/v1/content-approvals/{blog_item['content_id']}/keywords",
        headers={"X-CSRF-Token": csrf},
        json={
            "focus_keyphrase": "Fixed vs Dynamic Betting Odds",
            "secondary_keywords": ["Fixed odds vs dynamic odds comparison"],
            "anchor_text_variations": ["Fixed vs Dynamic Betting Odds"],
        },
    )
    assert kw_upd.status_code == 200
    assert kw_upd.json()["keyword_mapping"]["version"] >= 2

    # Check approved draft is STILL approved even if AI regeneration runs!
    gen_again = client.post(
        f"/api/v1/contents/{blog_item['content_id']}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={"trigger_type": "manual", "force_regenerate": True},
    )
    assert gen_again.status_code == 202
    gen_svc.execute_job(gen_again.json()["id"])
    posts_after = client.get(f"/api/v1/contents/{blog_item['content_id']}/social-posts").json()
    assert posts_after[0]["status"] == "approved"

    # 5. Re-run scan on UNCHANGED URLs:
    #    - Approved keywords MUST NOT be overwritten
    #    - Rejected URL MUST remain rejected (no duplicate approval requests)
    #    - No duplicate pending approvals or duplicate auto-gen jobs!
    scan2_res = client.post(
        f"/api/v1/websites/{site['id']}/scan",
        headers={"X-CSRF-Token": csrf},
        json={"scan_mode": "full", "trigger_type": "manual"},
    )
    assert scan2_res.status_code == 202
    executor.execute_scan(scan2_res.json()["id"])

    blog_after_scan2 = client.get(
        f"/api/v1/content-approvals/{blog_item['content_id']}"
    ).json()
    assert blog_after_scan2["status"] == "approved"
    assert (
        blog_after_scan2["keyword_mapping"]["focus_keyphrase"]
        == "Fixed vs Dynamic Betting Odds"
    )
    rej_after_scan2 = client.get(
        f"/api/v1/content-approvals/{rejected_item['content_id']}"
    ).json()
    assert rej_after_scan2["status"] == "rejected"
    # Total dispatched jobs must remain 2 (#1 auto-gen on approval + #2 manual gen_again),
    # and the manual post-keyword-update run must have bypassed stale cache (2 Gemini calls).
    assert len(memory_repos["dispatched_ai_jobs"]) == 2
    assert len(ai_client.calls) == 2

    # 5b. Scan 3 with meaningfully changed HTML transitions approved -> needs_rereview
    # while STILL preserving admin-curated/locked keywords.
    routes["https://bygame.ph/blog/fixed-odds-vs-dynamic-odds/"] = httpx.Response(
        200,
        text=(
            "<html><head><title>Fixed Odds vs Dynamic Odds: 2026 Update</title></head>"
            "<body><main><article><h1>Fixed Odds vs Dynamic Odds</h1>"
            "<p>Substantially expanded live odds analysis with new payout tiers.</p>"
            "</article></main></body></html>"
        ),
    )
    scan3_res = client.post(
        f"/api/v1/websites/{site['id']}/scan",
        headers={"X-CSRF-Token": csrf},
        json={"scan_mode": "full", "trigger_type": "manual"},
    )
    assert scan3_res.status_code == 202
    executor.execute_scan(scan3_res.json()["id"])
    blog_after_scan3 = client.get(
        f"/api/v1/content-approvals/{blog_item['content_id']}"
    ).json()
    assert blog_after_scan3["status"] == "needs_rereview"
    assert (
        blog_after_scan3["keyword_mapping"]["focus_keyphrase"]
        == "Fixed vs Dynamic Betting Odds"
    )
    # Re-approve updated content to keep map populated cleanly for Step 6 & Step 7
    reapprove_res = client.post(
        f"/api/v1/content-approvals/{blog_item['content_id']}/approve",
        headers={"X-CSRF-Token": csrf},
        json={"review_note": "Confirmed after edit"},
    )
    assert reapprove_res.status_code == 200
    assert reapprove_res.json()["auto_generation_job_id"] is None

    # 6. Cannibalization warning: homepage shares same focus keyphrase (non-blocking warning).
    cannibal_res = client.post(
        f"/api/v1/content-approvals/{home_item['content_id']}/approve",
        headers={"X-CSRF-Token": csrf},
        json={"focus_keyphrase": "Fixed vs Dynamic Betting Odds"},
    )
    assert cannibal_res.status_code == 200
    assert len(cannibal_res.json()["cannibalization_warnings"]) >= 1
    assert cannibal_res.json()["cannibalization_warnings"][0]["severity"] == "high"

    # Cross-website isolation: different website using SAME focus keyphrase must NOT warn!
    other_site = _create_website(client, csrf, name="Arena Sports", domain="arena.ph")
    other_c = content_repo.create(
        {
            "website_id": other_site["id"],
            "content_type": "page",
            "classification_method": "path",
            "title": "Odds Comparison Portal",
            "url": "https://arena.ph/odds",
            "canonical_url": "https://arena.ph/odds",
            "url_hash": "z" * 64,
            "markdown_content": "# Odds Comparison",
            "optimized_context": "Title: Odds Comparison Portal",
            "keywords": ["odds"],
            "discovery_sources": ["manual"],
            "content_hash": "hash-z",
            "word_count": 3,
            "extraction_status": "extracted",
            "status": "extracted",
        }
    )
    other_app = client.post(
        f"/api/v1/content-approvals/{other_c.id}/approve",
        headers={"X-CSRF-Token": csrf},
        json={"focus_keyphrase": "Fixed vs Dynamic Betting Odds"},
    )
    assert other_app.status_code == 200
    assert other_app.json()["cannibalization_warnings"] == []

    # 7. KeywordReuseService returns canonical URL, title, focus, secondary & anchor variations.
    reuse_res = client.get(
        f"/api/v1/content-approvals/websites/{site['id']}/approved-keywords"
    )
    assert reuse_res.status_code == 200
    entries = reuse_res.json()
    assert len(entries) >= 3
    first_entry = entries[0]
    assert {
        "website_id",
        "content_id",
        "canonical_url",
        "title",
        "content_type",
        "focus_keyphrase",
        "secondary_keywords",
        "anchor_text_variations",
        "approval_status",
    }.issubset(first_entry.keys())


def test_historical_baseline_approval_never_triggers_auto_generation_and_bulk_approve(
    app: FastAPI,
    auth_client: tuple[TestClient, str],
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: DatabaseDiagnostic,
) -> None:
    client, csrf = auth_client
    site = _create_website(client, csrf, name="Baseline Hub", domain="baselinehub.ph")
    _configure_provider_and_profile(
        app, client, csrf, test_settings, memory_repos, website_id=site["id"]
    )
    website_repo = app.dependency_overrides[get_website_repo]()
    website_repo.update(site["id"], {"initial_scan_completed": True})
    content_repo = app.dependency_overrides[get_content_repo]()

    hist_post = content_repo.create(
        {
            "website_id": site["id"],
            "content_type": "blog_post",
            "classification_method": "path",
            "title": "Old Archived Article",
            "url": "https://baselinehub.ph/blog/old-post",
            "canonical_url": "https://baselinehub.ph/blog/old-post",
            "url_hash": "h1" + "0" * 62,
            "markdown_content": "# Old Archived Article\n\nLegacy archive text.",
            "optimized_context": "Title: Old Archived Article",
            "keywords": ["legacy archive"],
            "discovery_sources": ["sitemap"],
            "content_hash": "hash-old",
            "word_count": 5,
            "extraction_status": "extracted",
            "status": "extracted",
            "is_historical_baseline": True,
            "published_at": utc_now_naive(),
        }
    )
    pending_post = content_repo.create(
        {
            "website_id": site["id"],
            "content_type": "blog_post",
            "classification_method": "path",
            "title": "Awaiting Fetch Post",
            "url": "https://baselinehub.ph/blog/pending-post",
            "canonical_url": "https://baselinehub.ph/blog/pending-post",
            "url_hash": "h2" + "0" * 62,
            "markdown_content": None,
            "optimized_context": None,
            "keywords": [],
            "discovery_sources": ["sitemap"],
            "content_hash": "hash-pend",
            "word_count": 0,
            "extraction_status": "pending",
            "status": "discovered",
            "is_historical_baseline": False,
        }
    )
    fresh_page = content_repo.create(
        {
            "website_id": site["id"],
            "content_type": "page",
            "classification_method": "path",
            "title": "Payment Methods PH",
            "url": "https://baselinehub.ph/payments",
            "canonical_url": "https://baselinehub.ph/payments",
            "url_hash": "h3" + "0" * 62,
            "markdown_content": "# Payment Methods\n\nGCash and Maya instant deposits.",
            "optimized_context": "Title: Payment Methods PH",
            "keywords": ["gcash payments"],
            "discovery_sources": ["sitemap"],
            "content_hash": "hash-pay",
            "word_count": 7,
            "extraction_status": "extracted",
            "status": "extracted",
            "is_historical_baseline": False,
        }
    )

    bulk_res = client.post(
        "/api/v1/content-approvals/bulk-approve",
        headers={"X-CSRF-Token": csrf},
        json={
            "content_ids": [hist_post.id, pending_post.id, fresh_page.id],
            "overrides": [
                {
                    "content_id": hist_post.id,
                    "focus_keyphrase": "Legacy Archive Guide",
                    "secondary_keywords": ["Archived FAQ", "Old Rules"],
                },
                {
                    "content_id": fresh_page.id,
                    "focus_keyphrase": "GCash Payment Methods PH",
                    "secondary_keywords": ["Maya instant deposit"],
                },
            ],
            "review_note": "Bulk approval batch check",
        },
    )
    assert bulk_res.status_code == 200, bulk_res.text
    bdata = bulk_res.json()
    assert set(bdata["approved_content_ids"]) == {hist_post.id, fresh_page.id}
    assert bdata["total_skipped"] == 1
    assert bdata["skipped_items"][0]["content_id"] == pending_post.id
    # Historical baseline blog_post MUST NOT auto-trigger AI generation!
    assert bdata["auto_generation_job_ids"] == []
    assert memory_repos["dispatched_ai_jobs"] == []
    page_after_bulk = client.get(f"/api/v1/content-approvals/{fresh_page.id}").json()
    assert page_after_bulk["keyword_mapping"]["focus_keyphrase"] == "GCash Payment Methods PH"
    assert page_after_bulk["keyword_mapping"]["secondary_keywords"] == ["Maya instant deposit"]

    # Game Page (`game_page`) classification, approval queue eligibility, and stats coverage
    game_content = content_repo.create(
        {
            "website_id": site["id"],
            "content_type": "game_page",
            "classification_method": "default_rule",
            "title": "Lucky 777 Live Baccarat",
            "url": "https://baselinehub.ph/games/lucky-777",
            "canonical_url": "https://baselinehub.ph/games/lucky-777",
            "url_hash": "g1" + "0" * 62,
            "markdown_content": "# Lucky 777 Live Baccarat\n\nLive dealer table rules and payouts.",
            "optimized_context": "Title: Lucky 777 Live Baccarat",
            "keywords": ["live baccarat", "lucky 777"],
            "discovery_sources": ["sitemap"],
            "content_hash": "hash-game-1",
            "word_count": 9,
            "extraction_status": "extracted",
            "status": "extracted",
            "is_historical_baseline": False,
        }
    )
    game_queue = client.get(
        "/api/v1/content-approvals",
        params={"website_id": site["id"], "content_type": "game_page"},
    )
    assert game_queue.status_code == 200
    assert any(item["content_id"] == game_content.id for item in game_queue.json()["items"])

    game_approve = client.post(
        f"/api/v1/content-approvals/{game_content.id}/approve",
        headers={"X-CSRF-Token": csrf},
        json={
            "content_type": "game_page",
            "focus_keyphrase": "Lucky 777 Live Baccarat",
            "secondary_keywords": ["Live baccarat rules", "Lucky 777 payouts"],
        },
    )
    assert game_approve.status_code == 200, game_approve.text
    assert game_approve.json()["item"]["content_type"] == "game_page"
    assert game_approve.json()["auto_generation_job_id"] is None

    c_stats = client.get("/api/v1/contents/stats", params={"website_id": site["id"]}).json()
    assert c_stats["game_page_count"] == 1
    gp_tab = client.get(
        "/api/v1/contents", params={"website_id": site["id"], "tab": "game_pages"}
    ).json()
    assert gp_tab["meta"]["total_items"] == 1
