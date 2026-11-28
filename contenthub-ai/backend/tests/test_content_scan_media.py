from __future__ import annotations

import io
from datetime import timedelta
from typing import Any

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.core.exceptions import ConflictError
from app.models.base import utc_now_naive
from app.schemas.health import ResourceThresholdsInfo, SystemResourcesInfo
from app.services.content.duplicate import compute_content_hash, find_near_duplicate
from app.services.content.extractor import ContentExtractionEngine
from app.services.content.markdown import html_to_clean_markdown, sanitize_article_html
from app.services.content.media import (
    MediaAssetProcessor,
    MediaValidationError,
    validate_image_bytes,
)
from app.services.monitoring.health_service import HealthService
from app.services.scan_executor import ScanExecutorService
from app.services.scanner.exceptions import SSRFBlockedError
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from tests.conftest import public_dns_resolver

SAMPLE_HOMEPAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <title>Example Portal — Fast Sports &amp; Editorial Insights</title>
  <meta name="description" content="Trusted editorial portal for technical SEO and guides." />
</head>
<body>
  <main>
    <h1>Welcome to Example Portal</h1>
    <p>Explore practical research, product comparisons, and industry guides.</p>
    <a href="/blog/technical-seo">Read Technical SEO Guide</a>
  </main>
</body>
</html>"""

SAMPLE_ARTICLE_V1 = """<!doctype html>
<html lang="en">
<head>
  <title>How Technical SEO Drives Sustainable Traffic</title>
  <link rel="canonical" href="https://example.com/blog/technical-seo?utm_source=test" />
  <meta name="description" content="A practical SEO guide on crawl budgets and canonicals." />
  <meta name="author" content="Maria Santos" />
  <meta property="og:image" content="https://example.com/images/seo-hero.png" />
  <meta property="article:published_time" content="2026-11-24T09:00:00Z" />
  <meta property="article:section" content="SEO" />
  <meta property="article:tag" content="Crawling" />
</head>
<body>
  <nav><a href="/login">Sign In</a></nav>
  <article>
    <h1>How Technical SEO Drives Sustainable Traffic</h1>
    <script>alert('xss')</script>
    <p onclick="evil()">
      Technical SEO ensures search engines can crawl, render, and index your most
      important pages efficiently without wasting server resources.
    </p>
    <h2>Canonical URL Hygiene</h2>
    <p>
      Always normalize tracking query parameters and serve consistent canonical link
      tags across paginated archives to prevent duplicate indexing.
    </p>
    <p>
      In our 2026 audit of 120 websites, clean canonical tags
      reduced duplicate crawl waste by 38% while improving index coverage.
    </p>
    <a href="javascript:alert(1)">Bad link</a>
    <a href="https://example.com/blog/sitemaps">Read sitemap guide</a>
  </article>
  <footer>Copyright 2026</footer>
</body>
</html>"""

SAMPLE_ARTICLE_V2 = SAMPLE_ARTICLE_V1.replace(
    "reduced duplicate crawl waste by 38%",
    "reduced duplicate crawl waste by 47% after adding HTTP ETag caching",
)


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(15, 118, 110)).save(buf, format="PNG")
    return buf.getvalue()


def test_content_extraction_sanitization_keywords_optimizer_and_near_duplicate(
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    sanitized = sanitize_article_html(SAMPLE_ARTICLE_V1)
    assert "<script" not in sanitized.lower()
    assert "onclick=" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()

    md = html_to_clean_markdown(SAMPLE_ARTICLE_V1)
    assert "Technical SEO ensures search engines" in md
    assert "alert('xss')" not in md

    engine = ContentExtractionEngine(settings=test_settings)
    extracted = engine.extract_from_html(
        SAMPLE_ARTICLE_V1,
        page_url="https://example.com/blog/technical-seo?utm_source=fb",
        domain="example.com",
    )
    assert extracted.content_type == "blog_post"
    assert extracted.canonical_url == "https://example.com/blog/technical-seo"
    assert extracted.author == "Maria Santos"
    assert extracted.categories == ["SEO"]
    assert extracted.tags == ["Crawling"]
    assert extracted.word_count >= 40
    assert len(extracted.keywords) >= 3
    assert "Title:" in extracted.optimized_context
    assert "How Technical SEO Drives Sustainable Traffic" in extracted.optimized_context
    assert len(extracted.optimized_context) <= test_settings.content_max_context_chars

    existing = memory_repos["contents"].create(
        {
            "website_id": 1,
            "content_type": "blog_post",
            "title": extracted.title,
            "url": "https://example.com/blog/other",
            "canonical_url": "https://example.com/blog/other",
            "url_hash": "0" * 64,
            "markdown_content": extracted.markdown_content,
            "content_hash": compute_content_hash(extracted.title, extracted.markdown_content),
        }
    )
    match = find_near_duplicate(
        title=extracted.title,
        markdown_content=extracted.markdown_content,
        existing_contents=[existing],
        threshold=85.0,
    )
    assert match is not None
    assert match[0] == existing.id
    assert match[1] >= 95.0


def test_media_validation_pillow_local_dedupe_and_ssrf_protection(
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    png = _png_bytes(80, 60)
    mime, w, h, checksum = validate_image_bytes(
        png,
        max_file_bytes=1_000_000,
        max_dimension_px=1000,
        declared_mime="image/png",
    )
    assert (mime, w, h) == ("image/png", 80, 60)
    assert len(checksum) == 64

    with pytest.raises(MediaValidationError):
        validate_image_bytes(b"corrupt", max_file_bytes=1000, max_dimension_px=1000)

    with pytest.raises(MediaValidationError):
        validate_image_bytes(png, max_file_bytes=1_000_000, max_dimension_px=32)

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(
            lambda _req: httpx.Response(200, content=png, headers={"Content-Type": "image/png"})
        ),
    )
    processor = MediaAssetProcessor(
        settings=test_settings,
        fetcher=fetcher,
        media_repo=memory_repos["media"],
    )

    first = processor.process_featured_image(
        source_url="https://example.com/images/seo-hero.png",
        website_id=1,
        storage_mode="local",
    )
    second = processor.process_featured_image(
        source_url="https://example.com/images/seo-hero-copy.png",
        website_id=1,
        storage_mode="local",
    )
    assert first is not None and second is not None
    assert first.id == second.id
    assert first.file_path is not None

    with pytest.raises(SSRFBlockedError):
        processor.process_featured_image(
            source_url="http://127.0.0.1/internal.png",
            website_id=1,
            storage_mode="local",
        )


def test_scan_lifecycle_dedupe_revisions_locking_stale_recovery_and_resource_guardian(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    site = memory_repos["websites"].create(
        {
            "category_id": 1,
            "name": "Ops Site",
            "brand_name": "Ops Brand",
            "domain": "example.com",
            "website_type": "static_html",
            "discovery_method": "auto",
            "rss_url": "https://example.com/feed.xml",
            "scan_interval_minutes": 60,
            "auto_scan": True,
            "next_scan_at": utc_now_naive() - timedelta(minutes=5),
        }
    )

    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Ops</title>
      <item>
        <title>How Technical SEO Drives Sustainable Traffic</title>
        <link>https://example.com/blog/technical-seo</link>
      </item>
    </channel></rss>"""

    article_version = [SAMPLE_ARTICLE_V1]
    img_bytes = _png_bytes()

    def mock_http(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == "https://example.com/":
            return httpx.Response(200, text=SAMPLE_HOMEPAGE_HTML)
        if url == "https://example.com/feed.xml":
            return httpx.Response(200, text=rss_xml)
        if url == "https://example.com/blog/technical-seo":
            return httpx.Response(200, text=article_version[0])
        if url == "https://example.com/images/seo-hero.png":
            return httpx.Response(200, content=img_bytes, headers={"Content-Type": "image/png"})
        return httpx.Response(404)

    class NormalHealthService(HealthService):
        def get_system_resources(
            self, *, effective_settings: dict[str, Any] | None = None
        ) -> SystemResourcesInfo:
            return SystemResourcesInfo(
                cpu_percent=12.0,
                cpu_cores=16,
                ram_percent=30.0,
                ram_used_mb=9000.0,
                ram_total_mb=31000.0,
                load_avg_1m=1.2,
                load_avg_5m=1.0,
                load_avg_15m=0.9,
                disk_percent=40.0,
                disk_free_gb=120.0,
                guardian_status="normal",
                guardian_reasons=[],
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

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(mock_http),
    )
    settings_service = SettingsService(
        settings=test_settings,
        settings_repo=memory_repos["settings"],
        activity_repo=memory_repos["activities"],
    )
    executor = ScanExecutorService(
        settings=test_settings,
        website_repo=memory_repos["websites"],
        source_config_repo=memory_repos["sources"],
        content_repo=memory_repos["contents"],
        scan_log_repo=memory_repos["scans"],
        media_repo=memory_repos["media"],
        activity_repo=memory_repos["activities"],
        health_service=NormalHealthService(
            settings=test_settings, db_checker=lambda: db_diagnostic_ok
        ),
        settings_service=settings_service,
        fetcher=fetcher,
        dispatcher=lambda _sid: None,
    )

    # 1. Enqueue first scan & verify active lock blocks duplicate scan.
    scan1 = executor.enqueue_scan(site.id, trigger_type="manual", dispatch=False)
    with pytest.raises(ConflictError):
        executor.enqueue_scan(site.id, trigger_type="manual", dispatch=False)

    res1 = executor.execute_scan(scan1.id)
    assert res1.status == "completed"
    # Aggregated discovery captures homepage (/) and blog post (/blog/technical-seo)
    assert res1.new_articles == 2
    assert res1.homepage_count == 1
    assert res1.blog_post_count == 1
    assert memory_repos["websites"].get_by_id(site.id).initial_scan_completed is True

    # 2. Second scan with identical content -> unchanged, zero duplicate rows.
    scan2 = executor.enqueue_scan(site.id, trigger_type="manual", dispatch=False)
    res2 = executor.execute_scan(scan2.id)
    assert res2.unchanged_articles == 2
    assert res2.new_articles == 0
    assert memory_repos["contents"].count_by_website(site.id) == 2

    # 3. Third scan with updated article body -> revision snapshot created & content updated.
    article_version[0] = SAMPLE_ARTICLE_V2
    scan3 = executor.enqueue_scan(site.id, trigger_type="manual", dispatch=False)
    res3 = executor.execute_scan(scan3.id)
    assert res3.updated_articles == 1
    assert res3.unchanged_articles == 1
    posts = [
        c
        for c in memory_repos["contents"].list_for_website(site.id)
        if c.content_type == "blog_post"
    ]
    assert len(posts) == 1
    art = posts[0]
    revs = memory_repos["contents"].list_revisions(art.id)
    assert len(revs) == 1
    assert revs[0].revision_number == 1
    assert art.status == "updated"

    # 4. Stale scan recovery recovers stuck scan and allows a fresh scan.
    stuck = memory_repos["scans"].create(
        website_id=site.id, scan_method="auto", trigger_type="manual", status="processing"
    )
    stuck.heartbeat_at = utc_now_naive() - timedelta(
        minutes=test_settings.scanner_stale_timeout_minutes + 5
    )
    scan4 = executor.enqueue_scan(site.id, trigger_type="manual", dispatch=False)
    assert memory_repos["scans"].get_by_id(stuck.id).status == "failed"
    assert scan4.status == "pending"
    memory_repos["scans"].update(scan4.id, {"status": "failed", "error_message": "Simulated crash"})

    retried = executor.retry_scan(scan4.id, user_id=1, ip_address="127.0.0.1", dispatch=False)
    assert retried.trigger_type == "retry"
    memory_repos["scans"].update(retried.id, {"status": "completed"})

    # 5. Resource Guardian pauses scanning under critical load.
    class ConstrainedHealthService(HealthService):
        def get_system_resources(
            self, *, effective_settings: dict[str, Any] | None = None
        ) -> SystemResourcesInfo:
            return SystemResourcesInfo(
                cpu_percent=92.5,
                cpu_cores=16,
                ram_percent=82.0,
                ram_used_mb=25000.0,
                ram_total_mb=31000.0,
                load_avg_1m=14.5,
                load_avg_5m=13.0,
                load_avg_15m=11.0,
                disk_percent=50.0,
                disk_free_gb=100.0,
                guardian_status="critical",
                guardian_reasons=["CPU usage (92.5%) reached critical threshold (85.0%)."],
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

    executor.health_service = ConstrainedHealthService(
        settings=test_settings, db_checker=lambda: db_diagnostic_ok
    )
    paused_scan = executor.enqueue_scan(site.id, trigger_type="manual", dispatch=False)
    paused_res = executor.execute_scan(paused_scan.id)
    assert paused_res.status == "paused"

    sched_summary = executor.run_due_scheduled_scans()
    assert sched_summary.paused_by_resource_guardian is True
    assert sched_summary.scans_executed == 0


def test_contents_media_and_scan_api_endpoints(
    app: Any,
    test_settings: Settings,
    auth_client: tuple[Any, str],
    memory_repos: dict[str, Any],
) -> None:
    from app.core.dependencies import get_http_fetcher

    client, csrf = auth_client

    site = memory_repos["websites"].create(
        {
            "category_id": 1,
            "name": "Lib Site",
            "brand_name": "Lib Brand",
            "domain": "example.com",
            "website_type": "wordpress",
            "discovery_method": "auto",
            "scan_interval_minutes": 360,
        }
    )
    media = memory_repos["media"].create(
        website_id=site.id,
        file_name="hero.png",
        file_path=None,
        source_url="https://example.com/images/seo-hero.png",
        mime_type="image/png",
        file_size=1234,
        width=800,
        height=600,
        alt_text="Hero",
        checksum="f" * 64,
    )
    content = memory_repos["contents"].create(
        {
            "website_id": site.id,
            "featured_media_id": media.id,
            "content_type": "blog_post",
            "title": "Initial Title",
            "url": "https://example.com/blog/technical-seo",
            "canonical_url": "https://example.com/blog/technical-seo",
            "url_hash": "a" * 64,
            "markdown_content": "Old body",
            "optimized_context": "Title: Initial Title",
            "categories": ["SEO"],
            "tags": ["Crawling"],
            "language": "en",
            "content_hash": "b" * 64,
            "word_count": 2,
            "extraction_status": "extracted",
            "status": "optimized",
        }
    )

    app.dependency_overrides[get_http_fetcher] = lambda: SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, text=SAMPLE_ARTICLE_V2)
            if str(req.url) == "https://example.com/blog/technical-seo"
            else httpx.Response(200, content=_png_bytes(), headers={"Content-Type": "image/png"})
        ),
    )

    list_resp = client.get(
        "/api/v1/contents",
        params={"website_id": site.id, "tag_or_category": "SEO"},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["meta"]["total_items"] == 1
    assert list_resp.json()["stats"]["blog_post_count"] == 1

    reproc = client.post(
        f"/api/v1/contents/{content.id}/reprocess",
        headers={"X-CSRF-Token": csrf},
    )
    assert reproc.status_code == 200
    assert reproc.json()["status"] == "updated"
    assert reproc.json()["revision_count"] == 1

    revs = client.get(f"/api/v1/contents/{content.id}/revisions")
    assert revs.status_code == 200
    assert len(revs.json()) == 1

    patch = client.patch(
        f"/api/v1/contents/{content.id}",
        headers={"X-CSRF-Token": csrf},
        json={"content_type": "page", "status": "archived"},
    )
    assert patch.status_code == 200
    assert patch.json()["status"] == "archived"
    assert patch.json()["content_type"] == "page"
    assert patch.json()["manual_classification_override"] is True

    media_list = client.get("/api/v1/media", params={"website_id": site.id})
    assert media_list.status_code == 200
    assert media_list.json()["meta"]["total_items"] >= 1
    assert client.get(f"/api/v1/media/{media.id}").status_code == 200
    media_file = client.get(
        f"/api/v1/media/{media.id}/file",
        follow_redirects=False,
    )
    assert media_file.status_code == 307
    assert media_file.headers["location"] == media.source_url
