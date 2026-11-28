from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cli import build_parser
from app.config import Settings
from app.core.dependencies import (
    get_ai_provider_client,
    get_ai_repo,
    get_content_repo,
    get_social_post_repo,
    get_social_profile_repo,
    get_website_repo,
)
from app.core.logging import redact_text
from app.models.base import utc_now_naive
from app.schemas.health import ResourceThresholdsInfo, SystemResourcesInfo
from app.services.ai.cache import compute_cache_key
from app.services.ai.context_builder import prepare_article_context, select_knowledge_sources
from app.services.ai.exceptions import AiPermanentError, AiTransientError
from app.services.ai.generation_service import AiGenerationService
from app.services.ai.model_registry import is_compatible_text_model, sort_models_free_first
from app.services.ai.prompt_builder import render_sandboxed_prompt
from app.services.ai.provider import ProviderGenerationResult, ProviderModelDescriptor
from app.services.monitoring.health_service import HealthService
from app.services.scan_executor import ScanExecutorService
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from tests.ai_memory_fakes import FakeGeminiProviderClient
from tests.conftest import public_dns_resolver


def _create_website(
    client: TestClient, csrf: str, *, name: str = "Bygame PH", domain: str = "bygame.ph"
) -> dict[str, Any]:
    cats = client.get("/api/v1/website-categories").json()["items"]
    casino = next((c for c in cats if c["slug"] == "casino"), cats[0])
    resp = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "category_id": casino["id"],
            "name": name,
            "brand_name": name,
            "domain": domain,
            "website_type": "nuxt",
            "discovery_method": "auto",
            "primary_language": "Taglish",
            "target_country": "Philippines",
            "tone": "Energetic and clear",
            "default_hashtags": ["#Bygame", "#GamingPH"],
            "restricted_keywords": ["guaranteedwin"],
            "auto_generate": True,
            "auto_generate_require_published_at": True,
            "auto_generate_context_mode": "optimized",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_provider(
    client: TestClient,
    csrf: str,
    *,
    name: str = "Primary Gemini Free",
    api_key: str = "AIzaSyFakeKeyValue9988776655",
    daily_request_limit: int = 100,
    daily_token_limit: int = 250000,
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/ai/providers",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "api_key": api_key,
            "selected_model": "gemini-3.5-flash-lite",
            "daily_request_limit": daily_request_limit,
            "daily_token_limit": daily_token_limit,
            "per_minute_request_limit": 20,
            "is_default": True,
            "is_active": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_extracted_content(
    app: FastAPI,
    website_id: int,
    *,
    url: str = "https://bygame.ph/blog/new-promo-2026",
    title: str = "New 2026 VIP Tournament Launch",
    content_type: str = "blog_post",
    extraction_status: str = "extracted",
    published_at: Any | None = "DEFAULT",
    is_historical_baseline: bool = False,
) -> Any:
    content_repo = app.dependency_overrides[get_content_repo]()
    pub = utc_now_naive() if published_at == "DEFAULT" else published_at
    return content_repo.create(
        {
            "website_id": website_id,
            "content_type": content_type,
            "classification_method": "path",
            "title": title,
            "meta_description": "Official announcement of the 2026 tournament series.",
            "url": url,
            "canonical_url": url,
            "url_hash": compute_cache_key_simple(url),
            "markdown_content": (
                f"# {title}\n\n"
                "Players across Manila can join qualifying rounds all week.\n"
                "Review full schedule, prize pool tiers, and official guidelines."
            ),
            "extracted_content": (
                f"{title}. Players across Manila can join qualifying rounds all week."
            ),
            "optimized_context": (
                f"Title: {title}\nURL: {url}\nSummary: Players in Manila join weekly qualifiers."
            ),
            "keywords": ["tournament", "manila", "bygame"],
            "discovery_sources": ["sitemap"],
            "content_hash": compute_cache_key_simple(f"{url}:{title}:{extraction_status}"),
            "word_count": 28,
            "extraction_status": extraction_status,
            "status": "extracted" if extraction_status == "extracted" else "failed",
            "published_at": pub,
            "is_historical_baseline": is_historical_baseline,
        }
    )


def compute_cache_key_simple(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _run_job_direct(
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
    job_id: int,
) -> Any:
    svc = AiGenerationService(
        settings=test_settings,
        ai_repo=app.dependency_overrides[get_ai_repo](),
        website_repo=app.dependency_overrides[get_website_repo](),
        category_repo=memory_repos["categories"],
        content_repo=app.dependency_overrides[get_content_repo](),
        social_profile_repo=app.dependency_overrides[get_social_profile_repo](),
        social_post_repo=app.dependency_overrides[get_social_post_repo](),
        activity_repo=memory_repos["activities"],
        health_service=HealthService(settings=test_settings, db_checker=lambda: db_diagnostic_ok),
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        provider_client=app.dependency_overrides[get_ai_provider_client](),
        dispatcher=lambda _jid: None,
    )
    return svc.execute_job(job_id)


def test_scenarios_01_to_05_social_profiles_multi_manual_encryption_and_disable(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
) -> None:
    client, csrf = auth_client
    site = _create_website(client, csrf)
    wid = site["id"]

    platforms = client.get("/api/v1/platforms").json()
    assert len(platforms) >= 8
    x_plat = next(p for p in platforms if p["platform_key"] == "twitter")
    assert x_plat["default_max_chars"] == 280
    assert x_plat["url_counts_as_chars"] == 23

    # Scenarios 1 & 2: Multiple Facebook profiles under same website + Manual profile without creds.
    raw_secret_token = "EAABsbCS1iHgBAUltraSecretFacebookToken9988"
    fb1 = client.post(
        f"/api/v1/websites/{wid}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": "facebook",
            "profile_name": "Bygame Main Page",
            "publishing_method": "api",
            "generation_enabled": True,
            "automatic_generation_enabled": True,
            "credentials": {
                "app_id": "1234567890",
                "app_secret": "fb-app-secret-value",
                "access_token": raw_secret_token,
            },
        },
    )
    assert fb1.status_code == 201, fb1.text
    fb1_data = fb1.json()
    assert fb1_data["auto_publish_enabled"] is False
    assert fb1_data["has_credentials"] is True
    assert raw_secret_token not in json.dumps(fb1_data, ensure_ascii=False)
    assert "••••" in json.dumps(fb1_data["credential_masks"], ensure_ascii=False)

    # Verify stored DB row uses Fernet ciphertext, not plaintext.
    profile_repo = app.dependency_overrides[get_social_profile_repo]()
    stored = profile_repo.get_by_id(fb1_data["id"])
    assert stored is not None
    assert stored.encrypted_access_token is not None
    assert raw_secret_token not in stored.encrypted_access_token

    # Auto-publish remains forbidden in Phase 3.
    bad_pub = client.post(
        f"/api/v1/websites/{wid}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": "facebook",
            "profile_name": "Blocked AutoPub",
            "auto_publish_enabled": True,
        },
    )
    assert bad_pub.status_code == 422

    # Scenario 2 & 3: Second Facebook profile (manual-only without credentials).
    fb2 = client.post(
        f"/api/v1/websites/{wid}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": "facebook",
            "profile_name": "Bygame VIP Community",
            "publishing_method": "manual",
            "generation_enabled": True,
            "automatic_generation_enabled": False,
        },
    )
    assert fb2.status_code == 201
    fb2_data = fb2.json()
    assert fb2_data["has_credentials"] is False
    assert fb2_data["credential_status"] == "not_configured"

    # Scenario 5: Disable generation on second profile and check destination preview.
    upd = client.patch(
        f"/api/v1/social-profiles/{fb2_data['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"generation_enabled": False},
    )
    assert upd.status_code == 200
    assert upd.json()["generation_enabled"] is False

    content = _seed_extracted_content(app, wid)
    dest_resp = client.get(f"/api/v1/contents/{content.id}/social-destinations")
    assert dest_resp.status_code == 200
    dest_ids = [p["id"] for p in dest_resp.json()["eligible_profiles"]]
    assert fb1_data["id"] in dest_ids
    assert fb2_data["id"] not in dest_ids

    # Check redaction guard on sensitive keys.
    assert raw_secret_token not in redact_text(f"access_token={raw_secret_token}")


def test_scenarios_06_to_09_gemini_config_test_models_and_failures(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
) -> None:
    client, csrf = auth_client
    fake_gemini = FakeGeminiProviderClient()
    app.dependency_overrides[get_ai_provider_client] = lambda: fake_gemini

    secret_key = "AIzaSyVerySecretGeminiKey1234567890"
    provider = _create_provider(client, csrf, api_key=secret_key)
    assert provider["has_api_key"] is True
    assert secret_key not in json.dumps(provider)
    assert provider["allow_paid_fallback"] is False

    # Scenario 7: Successful connection test with generation probe.
    test_ok = client.post(
        f"/api/v1/ai/providers/{provider['id']}/test",
        headers={"X-CSRF-Token": csrf},
        json={"verify_generation": True},
    )
    assert test_ok.status_code == 200
    assert test_ok.json()["connected"] is True
    assert test_ok.json()["model_available"] is True
    assert test_ok.json()["generation_probe_tokens"] == 12

    # Scenario 9: Dynamic model refresh & deprecated/non-text model filtering.
    fake_gemini.models.extend(
        [
            ProviderModelDescriptor(
                name="gemini-2.0-flash",
                display_name="Deprecated 2.0",
                supported_actions=("generateContent",),
            ),
            ProviderModelDescriptor(
                name="imagen-3.0-generate",
                display_name="Imagen",
                supported_actions=("generateImages",),
            ),
        ]
    )
    models_resp = client.get(f"/api/v1/ai/providers/{provider['id']}/models?refresh=true")
    assert models_resp.status_code == 200
    returned_names = [m["name"] for m in models_resp.json()["models"]]
    assert returned_names[0].endswith("flash-lite")
    assert "gemini-2.0-flash" not in returned_names
    assert "imagen-3.0-generate" not in returned_names
    assert not is_compatible_text_model(
        ProviderModelDescriptor(name="gemini-2.5-pro", display_name="2.5")
    )
    sorted_m = sort_models_free_first(fake_gemini.models)
    assert "flash-lite" in sorted_m[0].name

    # Scenario 8: Failed connection test sanitizes errors and sets status=failed.
    fake_gemini.next_error = AiPermanentError(
        f"Invalid API key {secret_key} for Gemini",
        code="GEMINI_AUTH_ERROR",
        status_code=401,
    )
    test_fail = client.post(
        f"/api/v1/ai/providers/{provider['id']}/test",
        headers={"X-CSRF-Token": csrf},
        json={"verify_generation": False},
    )
    assert test_fail.status_code == 200
    assert test_fail.json()["connected"] is False
    assert secret_key not in (test_fail.json()["error_detail"] or "")

    # Reject enabling paid fallback.
    paid_err = client.patch(
        f"/api/v1/ai/providers/{provider['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"allow_paid_fallback": True},
    )
    assert paid_err.status_code == 422


def test_scenarios_10_to_13_knowledge_profiles_overrides_and_stale_tracking(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
) -> None:
    client, csrf = auth_client
    fake_gemini = FakeGeminiProviderClient()
    app.dependency_overrides[get_ai_provider_client] = lambda: fake_gemini
    _create_provider(client, csrf)

    site = _create_website(client, csrf, name="Arena Sports", domain="arenasports.ph")
    wid = site["id"]

    _seed_extracted_content(
        app,
        wid,
        url="https://arenasports.ph/",
        title="Arena Sports Homepage",
        content_type="homepage",
    )
    _seed_extracted_content(
        app,
        wid,
        url="https://arenasports.ph/about-us",
        title="About Arena Sports PH",
        content_type="page",
    )
    _seed_extracted_content(
        app,
        wid,
        url="https://arenasports.ph/blog/archive-note",
        title="Minor Archive Post",
        content_type="blog_post",
    )

    # Verify compact source selection respects priority and cap.
    contents = app.dependency_overrides[get_content_repo]().list_for_website(wid, limit=20)
    site_model = app.dependency_overrides[get_website_repo]().get_by_id(wid)
    assert site_model is not None
    _ctx, refs, links, _fp = select_knowledge_sources(site_model, contents, max_items=2)
    assert refs[0]["content_type"] == "homepage"
    assert len(refs) == 2
    assert len(links) <= 2

    # Scenario 10: Generate knowledge profile via Gemini.
    gen_resp = client.post(
        f"/api/v1/websites/{wid}/knowledge-profile/generate",
        headers={"X-CSRF-Token": csrf},
        json={"preserve_manual_overrides": True},
    )
    assert gen_resp.status_code == 200, gen_resp.text
    kp1 = gen_resp.json()
    assert kp1["profile_version"] == 1
    assert kp1["status"] == "generated"
    assert kp1["is_outdated"] is False
    assert kp1["field_provenance"]["business_overview"] == "ai_generated"

    # Scenario 11: Manual edit & approval creates v2 and records admin provenance.
    patch_resp = client.patch(
        f"/api/v1/websites/{wid}/knowledge-profile",
        headers={"X-CSRF-Token": csrf},
        json={
            "target_audience": "Verified VIP Bettors in Metro Manila",
            "administrator_notes": "Always include 21+ responsible disclaimer.",
            "approve": True,
        },
    )
    assert patch_resp.status_code == 200
    kp2 = patch_resp.json()
    assert kp2["profile_version"] == 2
    assert kp2["status"] == "approved"
    assert kp2["field_provenance"]["target_audience"] == "admin"

    revs = client.get(f"/api/v1/websites/{wid}/knowledge-profile/revisions").json()
    assert [r["profile_version"] for r in revs] == [2, 1]

    # Scenario 12: Regenerating with preserve_manual_overrides=True retains admin edits.
    fake_gemini.custom_handler = lambda m, _sys, _usr, _schema: ProviderGenerationResult(
        raw_text=json.dumps(
            {
                "business_overview": "Fresh AI generated business summary.",
                "products_and_services": ["Live Odds"],
                "main_features": ["Fast Payouts"],
                "target_audience": "AI Overwrite Attempt Should Be Ignored",
                "recommended_writing_tone": "Calm and expert",
                "main_keywords": ["sports", "odds"],
                "content_pillars": ["Guides"],
                "relevant_publishing_restrictions": "21+ only",
            }
        ),
        model_name=m,
        latency_ms=80,
        measured_input_tokens=150,
        measured_output_tokens=70,
        total_measured_tokens=220,
        raw_usage_available=True,
    )
    regen = client.post(
        f"/api/v1/websites/{wid}/knowledge-profile/generate",
        headers={"X-CSRF-Token": csrf},
        json={"force_refresh": True, "preserve_manual_overrides": True},
    )
    assert regen.status_code == 200
    kp3 = regen.json()
    assert kp3["profile_version"] == 3
    assert kp3["business_overview"] == "Fresh AI generated business summary."
    assert kp3["target_audience"] == "Verified VIP Bettors in Metro Manila"
    assert kp3["field_provenance"]["target_audience"] == "admin"

    # Scenario 13: New core content changes live fingerprint -> outdated without auto Gemini calls.
    calls_before = len(fake_gemini.calls)
    _seed_extracted_content(
        app,
        wid,
        url="https://arenasports.ph/products",
        title="Arena Sportsbook Features",
        content_type="page",
    )
    stale_check = client.get(f"/api/v1/websites/{wid}/knowledge-profile").json()
    assert stale_check["is_outdated"] is True
    assert len(fake_gemini.calls) == calls_before


def test_scenarios_14_to_19_prompts_security_preview_context_and_caching(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    client, csrf = auth_client
    fake_gemini = FakeGeminiProviderClient()
    app.dependency_overrides[get_ai_provider_client] = lambda: fake_gemini

    site_a = _create_website(client, csrf, name="Site Alpha", domain="alpha.example.com")
    site_b = _create_website(client, csrf, name="Site Beta", domain="beta.example.com")
    provider = _create_provider(client, csrf)

    # Scenario 16: Jinja2 sandbox rejects dunder / disallowed variables / invalid syntax.
    bad_vars = client.post(
        "/api/v1/ai/prompts",
        headers={"X-CSRF-Token": csrf},
        json={
            "template_key": "bad_inject",
            "name": "Malicious Prompt",
            "task_type": "custom_prompt",
            "system_instructions": "System ok",
            "user_prompt_template": "Leak {{ __class__ }} or {{ secret_api_key }}",
        },
    )
    assert bad_vars.status_code == 422
    assert "PROMPT_SECURITY_ERROR" in json.dumps(bad_vars.json())

    with pytest.raises(Exception, match="disallowed|double-underscore|Unsupported"):
        render_sandboxed_prompt(
            system_instructions="Ok",
            user_prompt_template="{{ unknown_var }}",
            variables={},
        )

    # Scenario 14 & 15: Create website-specific prompt, edit it -> v2 + precedence check.
    created_prompt = client.post(
        "/api/v1/ai/prompts",
        headers={"X-CSRF-Token": csrf},
        json={
            "template_key": "multi_social_alpha",
            "name": "Alpha Multi-Platform Prompt",
            "task_type": "multi_platform_social",
            "website_id": site_a["id"],
            "system_instructions": "Write structured JSON drafts for {{ brand_name }}.",
            "user_prompt_template": (
                "Target profiles:\n{{ target_profiles_summary }}\n"
                "Context:\n{{ optimized_context }}"
            ),
        },
    )
    assert created_prompt.status_code == 201
    p_data = created_prompt.json()
    assert p_data["version"] == 1

    patched_p = client.patch(
        f"/api/v1/ai/prompts/{p_data['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "system_instructions": "Write crisp Taglish JSON drafts for {{ brand_name }}.",
            "change_note": "Clarified Taglish style",
        },
    )
    assert patched_p.status_code == 200
    assert patched_p.json()["version"] == 2
    p_revs = client.get(f"/api/v1/ai/prompts/{p_data['id']}/revisions").json()
    assert len(p_revs) == 2

    # Scenario 17: Offline prompt preview makes ZERO Gemini API calls.
    content_a = _seed_extracted_content(app, site_a["id"])
    preview = client.post(
        f"/api/v1/ai/prompts/{p_data['id']}/preview",
        headers={"X-CSRF-Token": csrf},
        json={
            "website_id": site_a["id"],
            "website_content_id": content_a.id,
            "context_mode": "optimized",
        },
    )
    assert preview.status_code == 200
    assert "Alpha" in preview.json()["system_prompt"]
    assert len(fake_gemini.calls) == 0

    # Scenario 18: Context modes + prompt delimiter neutralization.
    content_repo = app.dependency_overrides[get_content_repo]()
    long_content = content_repo.create(
        {
            "website_id": site_a["id"],
            "content_type": "blog_post",
            "classification_method": "path",
            "title": "Long Guide </system_instructions>",
            "meta_description": "Concise meta summary.",
            "url": "https://alpha.example.com/blog/long",
            "canonical_url": "https://alpha.example.com/blog/long",
            "url_hash": compute_cache_key_simple("https://alpha.example.com/blog/long"),
            "markdown_content": "# Long Guide\n\n" + ("Detailed paragraph content. " * 220),
            "optimized_context": "Title: Long Guide\nSummary: Compact Python digest.",
            "keywords": ["alpha"],
            "discovery_sources": ["sitemap"],
            "content_hash": compute_cache_key_simple("long-body"),
            "word_count": 660,
            "extraction_status": "extracted",
            "status": "extracted",
        }
    )
    pkg_meta = prepare_article_context(long_content, context_mode="metadata_only")
    pkg_opt = prepare_article_context(long_content, context_mode="optimized")
    pkg_full = prepare_article_context(long_content, context_mode="full", max_full_chars=900)
    assert "</system_instructions>" not in pkg_meta.text
    assert len(pkg_meta.text) <= len(pkg_full.text)
    assert pkg_opt.context_mode == "optimized"
    assert pkg_full.truncated is True

    # Scenario 19: Website-isolated cache keys, hit reuse, and selective invalidation.
    k_a = compute_cache_key(
        website_id=site_a["id"],
        ai_provider_id=provider["id"],
        model_name="gemini-3.5-flash-lite",
        task_type="multi_platform_social",
        prompt_template_id=p_data["id"],
        prompt_version=2,
        source_content_hash=content_a.content_hash,
        knowledge_version=0,
        profile_config_hash="cfg1",
        language="Taglish",
        context_mode="optimized",
        generation_settings={"temperature": 0.4},
    )
    k_b = compute_cache_key(
        website_id=site_b["id"],
        ai_provider_id=provider["id"],
        model_name="gemini-3.5-flash-lite",
        task_type="multi_platform_social",
        prompt_template_id=p_data["id"],
        prompt_version=2,
        source_content_hash=content_a.content_hash,
        knowledge_version=0,
        profile_config_hash="cfg1",
        language="Taglish",
        context_mode="optimized",
        generation_settings={"temperature": 0.4},
    )
    assert k_a != k_b

    # Configure profile on Site A, generate twice, second hits cache on a new un-drafted article?
    # Better: generate drafts, archive draft, regenerate -> hits cache without calling Gemini!
    prof_resp = client.post(
        f"/api/v1/websites/{site_a['id']}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={"platform_key": "facebook", "profile_name": "Alpha FB"},
    )
    assert prof_resp.status_code == 201

    job1 = client.post(
        f"/api/v1/contents/{content_a.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={"context_mode": "optimized"},
    ).json()
    res1 = _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, job1["id"])
    assert res1.status == "completed"
    assert res1.result_summary["api_calls"] == 1
    assert len(fake_gemini.calls) == 1

    # Cache hit on same profile config/content when archiving and re-running non-forced job:
    draft_id = res1.result_summary["created_draft_ids"][0]
    arch = client.post(
        f"/api/v1/social-posts/{draft_id}/archive",
        headers={"X-CSRF-Token": csrf},
    )
    assert arch.status_code == 200
    cache_job = client.post(
        f"/api/v1/contents/{content_a.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={"context_mode": "optimized", "force_regenerate": False},
    ).json()
    res2 = _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, cache_job["id"])
    assert res2.status == "completed"
    assert res2.result_summary["cache_hits"] == 1
    assert len(fake_gemini.calls) == 1

    stats = client.get("/api/v1/ai/cache/stats").json()
    assert stats["active_entries"] >= 1
    inv = client.post(
        "/api/v1/ai/cache/invalidate",
        headers={"X-CSRF-Token": csrf},
        json={"website_id": site_a["id"]},
    )
    assert inv.status_code == 200


def test_scenarios_20_to_29_generation_validation_x_urls_partial_and_draft_workflow(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    client, csrf = auth_client
    fake_gemini = FakeGeminiProviderClient()
    app.dependency_overrides[get_ai_provider_client] = lambda: fake_gemini
    _create_provider(client, csrf)

    site_empty = _create_website(client, csrf, name="NoProfile Site", domain="noprof.example.com")
    empty_content = _seed_extracted_content(app, site_empty["id"])

    # Scenario 21: Zero profiles guard blocks generation BEFORE calling Gemini.
    dest_empty = client.get(f"/api/v1/contents/{empty_content.id}/social-destinations").json()
    assert (
        dest_empty["empty_message"]
        == "No social profiles configured for content generation. "
        "Configure your website's social profiles first."
    )
    blocked = client.post(
        f"/api/v1/contents/{empty_content.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert blocked.status_code == 422
    assert len(fake_gemini.calls) == 0

    # Scenario 22: Non-extracted content and unsupported content type by default.
    site = _create_website(client, csrf, name="MultiBrand", domain="multibrand.ph")
    prof_x = client.post(
        f"/api/v1/websites/{site['id']}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={"platform_key": "twitter", "profile_name": "MultiBrand X"},
    ).json()
    prof_ig = client.post(
        f"/api/v1/websites/{site['id']}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={"platform_key": "instagram", "profile_name": "MultiBrand IG"},
    ).json()

    pending_item = _seed_extracted_content(
        app, site["id"], url="https://multibrand.ph/blog/pending", extraction_status="pending"
    )
    assert (
        client.post(
            f"/api/v1/contents/{pending_item.id}/generate-social",
            headers={"X-CSRF-Token": csrf},
            json={},
        ).status_code
        == 422
    )
    cat_item = _seed_extracted_content(
        app, site["id"], url="https://multibrand.ph/category/news", content_type="category"
    )
    assert (
        client.post(
            f"/api/v1/contents/{cat_item.id}/generate-social",
            headers={"X-CSRF-Token": csrf},
            json={},
        ).status_code
        == 422
    )

    # Scenario 23: Reject unexpected foreign social_profile_id returned by Gemini.
    blog = _seed_extracted_content(
        app,
        site["id"],
        url="https://multibrand.ph/blog/ultra-long-slug-parameter-testing-url-23-chars-guide",
    )
    fake_gemini.custom_handler = lambda m, _s, _u, _sch: ProviderGenerationResult(
        raw_text=json.dumps(
            {
                "drafts": [
                    {
                        "social_profile_id": 999999,
                        "platform": "twitter",
                        "caption": "Foreign profile hijack",
                        "hashtags": [],
                    }
                ]
            }
        ),
        model_name=m,
        latency_ms=50,
    )
    j_foreign = client.post(
        f"/api/v1/contents/{blog.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={},
    ).json()
    res_foreign = _run_job_direct(
        app, test_settings, memory_repos, db_diagnostic_ok, j_foreign["id"]
    )
    assert res_foreign.status == "failed"
    assert res_foreign.error_code == "AI_RESPONSE_VALIDATION_ERROR"
    assert client.get(f"/api/v1/contents/{blog.id}/social-posts").json() == []

    # Scenario 24 & 25: Partial batch failure + X 23-char URL counting + IG non-clickable URL note.
    fake_gemini.custom_handler = lambda m, _s, _u, _sch: ProviderGenerationResult(
        raw_text=json.dumps(
            {
                "drafts": [
                    {
                        "social_profile_id": prof_x["id"],
                        "platform": "twitter",
                        "caption": "Fast X launch note!",
                        "hashtags": ["#Launch", "#guaranteedwin"],
                        "cta": "Read now",
                    },
                    # Omitted prof_ig triggers partial validation failure for IG!
                ]
            }
        ),
        model_name=m,
        latency_ms=70,
        measured_input_tokens=200,
        measured_output_tokens=90,
        total_measured_tokens=290,
        raw_usage_available=True,
    )
    j_partial = client.post(
        f"/api/v1/contents/{blog.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={},
    ).json()
    res_partial = _run_job_direct(
        app, test_settings, memory_repos, db_diagnostic_ok, j_partial["id"]
    )
    assert res_partial.status == "partially_completed"
    assert str(prof_ig["id"]) in {str(k) for k in res_partial.result_summary["profile_errors"]}

    posts = client.get(f"/api/v1/contents/{blog.id}/social-posts").json()
    x_post = next(p for p in posts if p["social_profile_id"] == prof_x["id"])
    ig_post = next(p for p in posts if p["social_profile_id"] == prof_ig["id"])
    assert ig_post["status"] == "generation_failed"
    assert x_post["status"] == "pending_review"
    # Verify restricted hashtag filtered & X URL counted as 23 chars instead of 79+!
    assert "#guaranteedwin" not in [h.lower() for h in x_post["hashtags"]]
    assert x_post["character_count"] < len(x_post["assembled_content"])

    # Scenario 20, 26, 27, 28, 29: Manual edit + approve + preserve against duplicate gen + regen.
    fake_gemini.custom_handler = None
    edited = client.patch(
        f"/api/v1/social-posts/{x_post['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"caption": "Hand-tuned X announcement copy.", "cta_text": "Check details"},
    )
    assert edited.status_code == 200
    assert edited.json()["current_version"] == 2
    assert edited.json()["is_manually_edited"] is True

    approved = client.post(
        f"/api/v1/social-posts/{x_post['id']}/approve",
        headers={"X-CSRF-Token": csrf},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # Non-forced repeat run skips existing drafts & never overwrites approved draft.
    j_dup = client.post(
        f"/api/v1/contents/{blog.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={"force_regenerate": False},
    ).json()
    res_dup = _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, j_dup["id"])
    assert res_dup.status == "completed"
    assert len(client.get(f"/api/v1/contents/{blog.id}/social-posts").json()) == 2

    # Regenerating the approved X post explicitly creates v3 while preserving v1 & v2 revisions.
    j_regen = client.post(
        f"/api/v1/social-posts/{x_post['id']}/regenerate",
        headers={"X-CSRF-Token": csrf},
        json={"force": True},
    ).json()
    _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, j_regen["id"])
    revs = client.get(f"/api/v1/social-posts/{x_post['id']}/revisions").json()
    assert [r["version_number"] for r in revs] == [3, 2, 1]

    rejected = client.post(
        f"/api/v1/social-posts/{x_post['id']}/reject",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "Needs stronger hook"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_reason"] == "Needs stronger hook"

    archived = client.post(
        f"/api/v1/social-posts/{x_post['id']}/archive",
        headers={"X-CSRF-Token": csrf},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    # Ensure there is NO external publishing endpoint in Phase 3.
    assert client.post(
        f"/api/v1/social-posts/{x_post['id']}/publish",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 404


def test_scenarios_30_to_35_quotas_usage_workers_autoscan_cli_and_isolation(
    auth_client: tuple[TestClient, str],
    app: FastAPI,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    client, csrf = auth_client
    fake_gemini = FakeGeminiProviderClient()
    app.dependency_overrides[get_ai_provider_client] = lambda: fake_gemini

    # Scenario 30 & 31: Exhausted daily request quota defers job without fallback/key rotation.
    _create_provider(client, csrf, name="Tight Quota", daily_request_limit=1)
    site = _create_website(client, csrf, name="AutoGen Site", domain="autogen.ph")
    prof_auto = client.post(
        f"/api/v1/websites/{site['id']}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": "facebook",
            "profile_name": "Auto FB",
            "automatic_generation_enabled": True,
        },
    ).json()
    c1 = _seed_extracted_content(app, site["id"], url="https://autogen.ph/blog/post-1")
    c2 = _seed_extracted_content(app, site["id"], url="https://autogen.ph/blog/post-2")

    # First run returns raw_usage_available=False -> usage fields marked unknown / null cost.
    fake_gemini.custom_handler = lambda m, _s, _u, _sch: ProviderGenerationResult(
        raw_text=json.dumps(
            {
                "drafts": [
                    {
                        "social_profile_id": prof_auto["id"],
                        "platform": "facebook",
                        "caption": "Unknown token usage draft",
                    }
                ]
            }
        ),
        model_name=m,
        latency_ms=95,
        measured_input_tokens=None,
        measured_output_tokens=None,
        total_measured_tokens=None,
        raw_usage_available=False,
    )
    j1 = client.post(
        f"/api/v1/contents/{c1.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={},
    ).json()
    _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, j1["id"])

    history = client.get("/api/v1/ai/history").json()["items"]
    assert history[0]["token_usage_status"] == "unknown"
    usage = client.get("/api/v1/ai/usage").json()
    assert usage["estimated_cost_usd_month"] is None
    assert usage["quota_status"] == "daily_requests_exhausted"

    # Second job exceeds daily_request_limit=1 -> deferred safely without calling Gemini again.
    calls_at_limit = len(fake_gemini.calls)
    j2 = client.post(
        f"/api/v1/contents/{c2.id}/generate-social",
        headers={"X-CSRF-Token": csrf},
        json={},
    ).json()
    res_def = _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, j2["id"])
    assert res_def.status == "deferred"
    assert res_def.error_code == "QUOTA_DAILY_REQUESTS_EXHAUSTED"
    assert len(fake_gemini.calls) == calls_at_limit

    # Scenario 32: Retry / cancel & CSV history export.
    cancelled = client.post(f"/api/v1/ai/jobs/{j2['id']}/cancel", headers={"X-CSRF-Token": csrf})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    retried = client.post(f"/api/v1/ai/jobs/{j2['id']}/retry", headers={"X-CSRF-Token": csrf})
    assert retried.status_code == 202 and retried.json()["status"] == "queued"
    csv_resp = client.get("/api/v1/ai/history/export")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]

    # Scenario 33: Stale job recovery + retry backoff on transient error + Resource Guardian.
    ai_repo = app.dependency_overrides[get_ai_repo]()
    stale_job = ai_repo.create_job(
        {
            "job_uuid": "stale-test-uuid",
            "job_type": "social_generation",
            "trigger_type": "manual",
            "website_id": site["id"],
            "website_content_id": c2.id,
            "target_profile_ids_json": [prof_auto["id"]],
            "ai_provider_id": j2["ai_provider_id"],
            "context_mode": "optimized",
            "force_regenerate": False,
            "idempotency_key": "stale-idem-key",
            "status": "processing",
            "heartbeat_at": utc_now_naive() - timedelta(minutes=30),
            "attempt_count": 1,
            "max_attempts": 2,
        }
    )
    recovered = ai_repo.recover_stale_jobs(stale_minutes=15)
    assert len(recovered) == 1
    assert recovered[0].id == stale_job.id and recovered[0].status == "deferred"

    # Transient rate limit -> backoff deferral; critical health -> guardian deferral.
    fake_gemini.custom_handler = None
    ai_repo.update_provider(j2["ai_provider_id"], {"daily_request_limit": 500})
    fake_gemini.next_error = AiTransientError("429", code="GEMINI_RATE_LIMITED", status_code=429)
    res_rate = _run_job_direct(app, test_settings, memory_repos, db_diagnostic_ok, j2["id"])
    assert res_rate.status == "deferred" and res_rate.error_code == "GEMINI_RATE_LIMITED"

    class CriticalHealthService(HealthService):
        def get_system_resources(
            self, *, effective_settings: dict[str, Any] | None = None
        ) -> SystemResourcesInfo:
            return SystemResourcesInfo(
                cpu_percent=95.0,
                cpu_cores=16,
                ram_percent=90.0,
                ram_used_mb=28000.0,
                ram_total_mb=32000.0,
                load_avg_1m=18.0,
                load_avg_5m=15.0,
                load_avg_15m=14.0,
                disk_percent=40.0,
                disk_free_gb=200.0,
                guardian_status="critical",
                guardian_reasons=["CPU critical"],
                thresholds=ResourceThresholdsInfo(
                    cpu_warning_percent=65,
                    cpu_critical_percent=85,
                    ram_warning_percent=75,
                    load_avg_threshold=12.0,
                    max_concurrent_generation=1,
                    max_concurrent_browsers=1,
                    recheck_interval_minutes=5,
                ),
            )

    crit_gen_service = AiGenerationService(
        settings=test_settings,
        ai_repo=ai_repo,
        website_repo=app.dependency_overrides[get_website_repo](),
        category_repo=memory_repos["categories"],
        content_repo=app.dependency_overrides[get_content_repo](),
        social_profile_repo=app.dependency_overrides[get_social_profile_repo](),
        social_post_repo=app.dependency_overrides[get_social_post_repo](),
        activity_repo=memory_repos["activities"],
        health_service=CriticalHealthService(
            settings=test_settings, db_checker=lambda: db_diagnostic_ok
        ),
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        provider_client=fake_gemini,
        dispatcher=lambda _jid: None,
    )
    crit_job = crit_gen_service.execute_job(stale_job.id)
    assert crit_job.status == "deferred"
    assert "critical" in (crit_job.defer_reason or "").lower()

    # Scenario 34: ScanExecutor auto-generation hooks strictly on NEW post-baseline blog_post.
    website_repo = app.dependency_overrides[get_website_repo]()
    content_repo = app.dependency_overrides[get_content_repo]()
    baseline_site = _create_website(client, csrf, name="ScanAuto Site", domain="scanauto.ph")
    client.post(
        f"/api/v1/websites/{baseline_site['id']}/social-profiles",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_key": "facebook",
            "profile_name": "ScanAuto FB",
            "automatic_generation_enabled": True,
        },
    )

    site_obj = website_repo.update(baseline_site["id"], {"initial_scan_completed": True})
    assert site_obj is not None
    enqueued_auto: list[int] = []

    class TrackingGenService(AiGenerationService):
        def enqueue_auto_scan_generation(
            self, *, website: Any, content: Any
        ) -> Any:
            res = super().enqueue_auto_scan_generation(website=website, content=content)
            if res is not None:
                enqueued_auto.append(res.id)
            return res

    tracking_gen = TrackingGenService(
        settings=test_settings,
        ai_repo=ai_repo,
        website_repo=website_repo,
        category_repo=memory_repos["categories"],
        content_repo=content_repo,
        social_profile_repo=app.dependency_overrides[get_social_profile_repo](),
        social_post_repo=app.dependency_overrides[get_social_post_repo](),
        activity_repo=memory_repos["activities"],
        health_service=HealthService(settings=test_settings, db_checker=lambda: db_diagnostic_ok),
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        provider_client=fake_gemini,
        dispatcher=lambda _jid: None,
    )

    # Historical baseline, undated blog_post, or page must NOT auto-enqueue!
    hist_c = _seed_extracted_content(
        app,
        baseline_site["id"],
        url="https://scanauto.ph/blog/old",
        is_historical_baseline=True,
    )
    undated_c = _seed_extracted_content(
        app,
        baseline_site["id"],
        url="https://scanauto.ph/blog/undated",
        published_at=None,
    )
    page_c = _seed_extracted_content(
        app,
        baseline_site["id"],
        url="https://scanauto.ph/about",
        content_type="page",
    )
    new_blog = _seed_extracted_content(
        app,
        baseline_site["id"],
        url="https://scanauto.ph/blog/fresh-post",
    )
    assert (
        tracking_gen.enqueue_auto_scan_generation(website=site_obj, content=hist_c) is None
    )
    assert (
        tracking_gen.enqueue_auto_scan_generation(website=site_obj, content=undated_c) is None
    )
    assert (
        tracking_gen.enqueue_auto_scan_generation(website=site_obj, content=page_c) is None
    )
    assert (
        tracking_gen.enqueue_auto_scan_generation(website=site_obj, content=new_blog)
        is not None
    )
    assert len(enqueued_auto) == 1

    # Also verify ScanExecutorService holds the ai_generation_service wiring without regression.
    executor = ScanExecutorService(
        settings=test_settings,
        website_repo=website_repo,
        source_config_repo=memory_repos["sources"],
        content_repo=content_repo,
        scan_log_repo=memory_repos["scans"],
        media_repo=memory_repos["media"],
        activity_repo=memory_repos["activities"],
        health_service=HealthService(settings=test_settings, db_checker=lambda: db_diagnostic_ok),
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        fetcher=SafeHttpFetcher(
            settings=test_settings,
            resolver=public_dns_resolver,
            transport=httpx.MockTransport(lambda _r: httpx.Response(404)),
        ),
        dispatcher=lambda _sid: None,
        ai_generation_service=tracking_gen,
    )
    assert executor.ai_generation_service is tracking_gen

    # Scenario 35: CLI argument parsing for worker commands.
    parser = build_parser()
    args_single = parser.parse_args(["run-ai-job", "--job-id", "19"])
    args_batch = parser.parse_args(["run-pending-ai-jobs", "--limit", "5"])
    assert args_single.command == "run-ai-job" and args_single.job_id == 19
    assert args_batch.command == "run-pending-ai-jobs" and args_batch.limit == 5
