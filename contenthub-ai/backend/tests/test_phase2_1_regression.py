from __future__ import annotations

import gzip
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas.health import ResourceThresholdsInfo, SystemResourcesInfo
from app.services.monitoring.health_service import HealthService
from app.services.scan_executor import ScanExecutorService
from app.services.scanner.classifier import classify_url
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from tests.conftest import public_dns_resolver


def _make_executor(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
    handler: Any,
) -> ScanExecutorService:
    class NormalHealthService(HealthService):
        def get_system_resources(
            self, *, effective_settings: dict[str, Any] | None = None
        ) -> SystemResourcesInfo:
            return SystemResourcesInfo(
                cpu_percent=15.0,
                cpu_cores=16,
                ram_percent=30.0,
                ram_used_mb=8000.0,
                ram_total_mb=32000.0,
                load_avg_1m=1.0,
                load_avg_5m=1.0,
                load_avg_15m=1.0,
                disk_percent=30.0,
                disk_free_gb=200.0,
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
        transport=httpx.MockTransport(handler),
    )
    return ScanExecutorService(
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
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        fetcher=fetcher,
        dispatcher=lambda _sid: None,
    )


def _page_html(
    title: str, body: str, *, jsonld_type: str | None = None, og_type: str | None = None
) -> str:
    extra_meta = f'<meta property="og:type" content="{og_type}" />' if og_type else ""
    extra_jsonld = (
        f'<script type="application/ld+json">'
        f'{{"@type": "{jsonld_type}", "headline": "{title}"}}</script>'
        if jsonld_type
        else ""
    )
    return (
        f"<!doctype html><html lang='en'><head><title>{title}</title>"
        f"<meta name='description' content='{title} summary overview.' />"
        f"{extra_meta}{extra_jsonld}</head><body><main><h1>{title}</h1>"
        f"<p>{body}</p></main></body></html>"
    )


def test_scenario_01_and_02_independent_website_registration_and_categories(
    auth_client: tuple[TestClient, str],
) -> None:
    """Scenarios 1 & 2: Register website independently + full category CRUD/archive/delete guard."""
    client, csrf = auth_client

    cat = client.post(
        "/api/v1/website-categories",
        headers={"X-CSRF-Token": csrf},
        json={"name": "iGaming Info", "description": "Guides"},
    ).json()
    renamed = client.patch(
        f"/api/v1/website-categories/{cat['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"name": "iGaming Guides"},
    ).json()
    assert renamed["name"] == "iGaming Guides"

    site = client.post(
        "/api/v1/websites",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Bygame Casino",
            "brand_name": "Bygame",
            "domain": "https://bygame.ph/",
            "category_id": cat["id"],
            "primary_language": "Taglish",
            "website_type": "nuxt",
        },
    )
    assert site.status_code == 201
    assert site.json()["brand_name"] == "Bygame"
    assert site.json()["category_id"] == cat["id"]

    # Deleting assigned category is rejected
    assert (
        client.delete(
            f"/api/v1/website-categories/{cat['id']}", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 409
    )


def test_scenario_03_04_10_aggregated_discovery_304_isolation_and_deduplication(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    """Scenarios 3, 4 & 10: RSS + Sitemap aggregate, 304 keeps prior URLs, and dedupe merges."""
    site = memory_repos["websites"].create(
        {
            "category_id": 2,
            "name": "Bygame",
            "brand_name": "Bygame",
            "domain": "example.com",
            "website_type": "nuxt",
            "discovery_method": "auto",
            "rss_url": "https://example.com/feed.xml",
            "sitemap_url": "https://example.com/sitemap.xml",
        }
    )

    rss_xml = """<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
      <item><title>Shared Post</title><link>https://example.com/blog/shared-post</link></item>
      <item><title>RSS Only Post</title><link>https://example.com/blog/rss-only</link></item>
    </channel></rss>"""
    sitemap_xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/</loc></url>
      <url><loc>https://example.com/blog/shared-post?utm_source=sitemap</loc></url>
      <url><loc>https://example.com/about-us</loc></url>
      <url><loc>https://example.com/blog/sitemap-only</loc></url>
    </urlset>"""

    rss_return_304 = [False]

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == "https://example.com/feed.xml":
            if rss_return_304[0] or req.headers.get("if-none-match") == '"rss-v1"':
                return httpx.Response(304, headers={"ETag": '"rss-v1"'})
            return httpx.Response(200, text=rss_xml, headers={"ETag": '"rss-v1"'})
        if url == "https://example.com/sitemap.xml":
            return httpx.Response(200, text=sitemap_xml, headers={"ETag": '"sm-v1"'})
        if url == "https://example.com/":
            return httpx.Response(
                200,
                text=_page_html("Home", "Homepage intro and sections")
                + "<a href='/blog/shared-post'>Shared</a>",
            )
        return httpx.Response(
            200, text=_page_html(f"Title for {url}", f"Unique body content for {url}")
        )

    executor = _make_executor(test_settings, memory_repos, db_diagnostic_ok, handler)

    # First full scan: RSS + Sitemap + Homepage aggregate without duplicate URL rows
    s1 = executor.enqueue_scan(site.id, scan_mode="full", dispatch=False)
    r1 = executor.execute_scan(s1.id)
    assert r1.status == "completed"
    urls_in_db = {c.canonical_url: c for c in memory_repos["contents"].list_for_website(site.id)}
    assert set(urls_in_db.keys()) == {
        "https://example.com/",
        "https://example.com/blog/shared-post",
        "https://example.com/blog/rss-only",
        "https://example.com/about-us",
        "https://example.com/blog/sitemap-only",
    }
    # Scenario 10: shared-post appeared in RSS + Sitemap + Homepage HTML -> merged sources, 1 row
    shared = urls_in_db["https://example.com/blog/shared-post"]
    assert "rss" in shared.discovery_sources
    assert "sitemap" in shared.discovery_sources

    # Scenario 4: Second incremental scan -> RSS 304 Not Modified, Sitemap still yields new URL
    rss_return_304[0] = True
    sitemap_xml = sitemap_xml.replace(
        "</urlset>",
        "<url><loc>https://example.com/promos</loc></url></urlset>",
    )
    s2 = executor.enqueue_scan(site.id, scan_mode="incremental", dispatch=False)
    r2 = executor.execute_scan(s2.id)
    assert r2.status == "completed"
    assert (
        memory_repos["contents"].get_by_id(urls_in_db["https://example.com/blog/rss-only"].id)
        is not None
    )
    assert any(
        c.canonical_url == "https://example.com/promos"
        for c in memory_repos["contents"].list_for_website(site.id)
    )


def test_scenario_05_06_07_multiple_custom_php_nested_and_gzip_sitemaps(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    """Scenarios 5, 6 & 7: Multiple, custom .php, nested indexes, and gzipped sitemaps."""
    site = memory_repos["websites"].create(
        {
            "category_id": 2,
            "name": "Multi Sitemap Site",
            "brand_name": "Multi",
            "domain": "example.com",
            "website_type": "custom_php",
            "discovery_method": "auto",
            "sitemap_url": "https://example.com/custom-map.php",
        }
    )

    root_php_index = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/nested/sub-index.xml</loc></sitemap>
      <sitemap><loc>https://example.com/sitemap-blog.xml.gz</loc></sitemap>
    </sitemapindex>"""
    sub_index = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
    </sitemapindex>"""
    pages_xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/about-us</loc></url>
      <url><loc>https://example.com/game/golden-slots</loc></url>
    </urlset>"""
    blog_gz = gzip.compress(
        b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/blog/nested-gz-post</loc></url>
        </urlset>"""
    )
    robots_sitemap_xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/sitemap-only-extra</loc></url>
    </urlset>"""

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nSitemap: https://example.com/extra-robots-sitemap.xml\n",
            )
        if url == "https://example.com/custom-map.php":
            return httpx.Response(200, text=root_php_index, headers={"Content-Type": "text/html"})
        if url == "https://example.com/nested/sub-index.xml":
            return httpx.Response(200, text=sub_index)
        if url == "https://example.com/sitemap-pages.xml":
            return httpx.Response(200, text=pages_xml)
        if url == "https://example.com/sitemap-blog.xml.gz":
            return httpx.Response(200, content=blog_gz)
        if url == "https://example.com/extra-robots-sitemap.xml":
            return httpx.Response(200, text=robots_sitemap_xml)
        return httpx.Response(200, text=_page_html(url, f"Extracted body for {url}"))

    executor = _make_executor(test_settings, memory_repos, db_diagnostic_ok, handler)
    scan = executor.enqueue_scan(site.id, scan_mode="full", dispatch=False)
    res = executor.execute_scan(scan.id)
    assert res.status == "completed"
    discovered_urls = {c.canonical_url for c in memory_repos["contents"].list_for_website(site.id)}
    assert {
        "https://example.com/",
        "https://example.com/about-us",
        "https://example.com/game/golden-slots",
        "https://example.com/blog/nested-gz-post",
        "https://example.com/sitemap-only-extra",
    }.issubset(discovered_urls)
    assert len(res.discovered_sitemaps) >= 4


@pytest.mark.parametrize(
    ("total_urls", "max_per_run", "batch_size"),
    [
        (
            160,
            200,
            50,
        ),  # Scenario 8: >100 URLs all discovered & extracted in 1 run (zero 100 truncation)
        (
            1050,
            400,
            100,
        ),  # Scenario 9: >1,000 URLs discovered, batched across runs, resumable to completion
    ],
)
def test_scenario_08_and_09_large_sitemap_discovery_batching_and_resume(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
    total_urls: int,
    max_per_run: int,
    batch_size: int,
) -> None:
    site = memory_repos["websites"].create(
        {
            "category_id": 2,
            "name": "Large Site",
            "brand_name": "Large",
            "domain": "example.com",
            "website_type": "wordpress",
            "discovery_method": "auto",
            "sitemap_url": "https://example.com/sitemap.xml",
            "crawl_batch_size": batch_size,
            "crawl_max_urls_per_run": max_per_run,
        }
    )

    locs = "\n".join(
        f"<url><loc>https://example.com/blog/post-{i}</loc></url>" for i in range(1, total_urls + 1)
    )
    large_sitemap = f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == "https://example.com/sitemap.xml":
            return httpx.Response(200, text=large_sitemap)
        return httpx.Response(200, text=_page_html(f"Title {url}", f"Content body for {url} " * 5))

    executor = _make_executor(test_settings, memory_repos, db_diagnostic_ok, handler)
    s1 = executor.enqueue_scan(site.id, scan_mode="full", dispatch=False)
    r1 = executor.execute_scan(s1.id)

    total_expected = total_urls + 1  # sitemap URLs + homepage '/'
    assert memory_repos["contents"].count_by_website(site.id) == min(total_expected, max_per_run)
    assert r1.urls_found == total_expected

    if total_urls <= max_per_run:
        assert r1.status == "completed"
        assert r1.urls_pending_extraction == 0
        assert r1.articles_processed == total_expected
    else:
        # Scenario 9: Run 1 paused cleanly as incomplete with remaining pending items persisted
        assert r1.status == "incomplete"
        assert r1.articles_processed == max_per_run
        assert r1.urls_pending_extraction == total_expected - max_per_run

        s2 = executor.enqueue_scan(site.id, scan_mode="resume", dispatch=False)
        r2 = executor.execute_scan(s2.id)
        assert r2.status == "incomplete"
        assert r2.articles_processed == max_per_run

        s3 = executor.enqueue_scan(site.id, scan_mode="resume", dispatch=False)
        r3 = executor.execute_scan(s3.id)
        assert r3.status == "completed"
        assert r3.urls_pending_extraction == 0
        stats = memory_repos["contents"].get_stats(website_id=site.id)
        assert stats["total_discovered"] == total_expected
        assert stats["total_extracted"] == total_expected
        assert stats["pending_count"] == 0


def test_scan_ignores_email_protection_and_redirects(
    test_settings: Settings, memory_repos: dict[str, Any], db_diagnostic_ok: Any
) -> None:
    site = memory_repos["websites"].create({
        "category_id": 2, "name": "Example", "brand_name": "Example",
        "domain": "example.com", "website_type": "wordpress", "discovery_method": "auto",
        "sitemap_url": "https://example.com/sitemap.xml",
    })
    email_url = "https://example.com/cdn-cgi/l/email-protection#abc"
    redirect_url = "https://example.com/old-page"
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{email_url}</loc></url><url><loc>{redirect_url}</loc></url></urlset>"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap)
        if req.url.path == "/old-page":
            return httpx.Response(301, headers={"Location": "/new-page"})
        return httpx.Response(200, text=_page_html("Home", "Homepage text " * 10))

    executor = _make_executor(test_settings, memory_repos, db_diagnostic_ok, handler)
    scan = executor.enqueue_scan(site.id, scan_mode="full", dispatch=False)
    result = executor.execute_scan(scan.id)
    items, _ = memory_repos["scans"].list_scan_items(scan.id, page=1, page_size=100)
    ignored = {item.failure_reason for item in items if item.status == "excluded"}
    assert {"ignored_email_protection", "ignored_redirect"} <= ignored
    assert result.failed_articles == 0
    urls = {row.url for row in memory_repos["contents"].list_for_website(site.id)}
    assert email_url not in urls and redirect_url not in urls


def test_scenario_11_to_16_deterministic_classification_and_custom_rules(
    memory_repos: dict[str, Any],
) -> None:
    """Scenarios 11-16: Homepage, Page, Blog Index, Blog Post, Taxonomy/Archive, Custom Rules."""
    assert classify_url("https://bygame.ph/", domain="bygame.ph").content_type == "homepage"
    assert classify_url("https://bygame.ph/about-us/", domain="bygame.ph").content_type == "page"
    assert classify_url("https://bygame.ph/promos/", domain="bygame.ph").content_type == "page"
    assert classify_url("https://bygame.ph/games/", domain="bygame.ph").content_type == "page"
    assert (
        classify_url("https://bygame.ph/game/sample-game/", domain="bygame.ph").content_type
        == "game_page"
    )
    assert (
        classify_url("https://bygame.ph/games/live-baccarat/", domain="bygame.ph").content_type
        == "game_page"
    )
    assert (
        classify_url("https://bygame.ph/games/category/slots/", domain="bygame.ph").content_type
        == "category"
    )
    assert classify_url("https://bygame.ph/blog/", domain="bygame.ph").content_type == "blog_index"
    assert classify_url("https://bygame.ph/blogs", domain="bygame.ph").content_type == "blog_index"
    assert (
        classify_url("https://bygame.ph/blog/sample-post/", domain="bygame.ph").content_type
        == "blog_post"
    )
    assert (
        classify_url("https://bygame.ph/blogs/sample-post", domain="bygame.ph").content_type
        == "blog_post"
    )
    assert (
        classify_url("https://bygame.ph/blog/category/sports/", domain="bygame.ph").content_type
        == "category"
    )
    assert classify_url("https://bygame.ph/tag/example/", domain="bygame.ph").content_type == "tag"
    assert (
        classify_url("https://bygame.ph/author/example/", domain="bygame.ph").content_type
        == "archive"
    )

    # Scenario 16: Website-specific URL classification rules override heuristics by priority
    r1 = memory_repos["sources"].create_rule(
        {
            "website_id": 1,
            "pattern": "/promo/*",
            "target_content_type": "custom",
            "match_mode": "glob",
            "priority": 20,
            "is_enabled": True,
        }
    )
    r2 = memory_repos["sources"].create_rule(
        {
            "website_id": 1,
            "pattern": "/guides/*",
            "target_content_type": "blog_post",
            "match_mode": "prefix",
            "priority": 10,
            "is_enabled": True,
        }
    )
    rules = [r1, r2]
    assert (
        classify_url(
            "https://bygame.ph/promo/vip-bonus", domain="bygame.ph", custom_rules=rules
        ).content_type
        == "custom"
    )
    assert (
        classify_url(
            "https://bygame.ph/guides/welcome", domain="bygame.ph", custom_rules=rules
        ).content_type
        == "blog_post"
    )


def test_scenario_17_to_22_manual_override_no_metadata_failure_retry_tabs_and_revisions(
    app: Any,
    test_settings: Settings,
    auth_client: tuple[TestClient, str],
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    """Scenarios 17-22: Manual override, metadata-less page, failure retry, tabs, and revisions."""
    client, csrf = auth_client

    site = memory_repos["websites"].create(
        {
            "category_id": 2,
            "name": "Full Coverage Site",
            "brand_name": "FullCov",
            "domain": "example.com",
            "website_type": "nuxt",
            "discovery_method": "auto",
            "sitemap_url": "https://example.com/sitemap.xml",
        }
    )

    fail_broken_url = [True]
    page_version = ["Version 1 concise overview text for the casino promo."]

    sitemap_xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/</loc></url>
      <url><loc>https://example.com/about-us</loc></url>
      <url><loc>https://example.com/blogs</loc></url>
      <url><loc>https://example.com/blog/win-big</loc></url>
      <url><loc>https://example.com/blog/category/sports</loc></url>
      <url><loc>https://example.com/broken-404</loc></url>
    </urlset>"""

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == "https://example.com/sitemap.xml":
            return httpx.Response(200, text=sitemap_xml)
        if url == "https://example.com/broken-404":
            if fail_broken_url[0]:
                return httpx.Response(404, text="Not Found")
            return httpx.Response(
                200, text=_page_html("Recovered Page", "Recovered body content now available.")
            )
        if url == "https://example.com/about-us":
            # Scenario 18: Plain landing page WITHOUT <article>, author, or published_at metadata
            return httpx.Response(
                200,
                text=(
                    "<!doctype html><html><head><title>About FullCov</title></head>"
                    f"<body><div class='hero'><h1>About FullCov</h1>"
                    f"<p>{page_version[0]}</p></div></body></html>"
                ),
            )
        return httpx.Response(
            200, text=_page_html(f"Page {url}", f"Rich paragraph text for {url}.")
        )

    executor = _make_executor(test_settings, memory_repos, db_diagnostic_ok, handler)

    # First Full Scan -> extracts 5 URLs & records 1 HTTP 404 failure cleanly
    s1 = executor.enqueue_scan(site.id, scan_mode="full", dispatch=False)
    r1 = executor.execute_scan(s1.id)
    assert r1.status == "partially_completed"
    # Scenario 21: Scan counts strictly match DB items
    assert r1.urls_found == 6
    assert r1.articles_processed == 5
    assert r1.new_articles == 5
    assert r1.failed_articles == 1
    assert r1.urls_found == (
        r1.new_articles
        + r1.updated_articles
        + r1.unchanged_articles
        + r1.failed_articles
        + r1.excluded_count
        + r1.urls_pending_extraction
    )

    # Verify /scans/{id}/items returns inspectable failure details
    items_resp = client.get(f"/api/v1/scans/{r1.id}/items", params={"failures_only": True})
    assert items_resp.status_code == 200
    assert items_resp.json()["meta"]["total_items"] == 1
    assert items_resp.json()["items"][0]["http_status"] == 404

    # Scenario 20: Content Library tab counts & filtering match DB stats
    stats = client.get("/api/v1/contents/stats", params={"website_id": site.id}).json()
    assert stats["total_discovered"] == 6
    assert stats["total_extracted"] == 5
    assert stats["homepage_count"] == 1
    assert stats["page_count"] == 2  # /about-us (extracted) + /broken-404 (failed)
    assert stats["blog_index_count"] == 1
    assert stats["blog_post_count"] == 1
    assert stats["other_count"] == 1  # /blog/category/sports -> category
    assert stats["failed_count"] == 1

    for tab, expected_count in [
        ("all", 6),
        ("homepage", 1),
        ("pages", 2),
        ("blog_posts", 1),
        ("blog_indexes", 1),
        ("other", 1),
        ("failed", 1),
    ]:
        tab_resp = client.get("/api/v1/contents", params={"website_id": site.id, "tab": tab})
        assert tab_resp.status_code == 200
        assert tab_resp.json()["meta"]["total_items"] == expected_count

    # Scenario 17: Manual reclassify preserved across next scan & creates revision snapshot
    about_row = next(
        c
        for c in memory_repos["contents"].list_for_website(site.id)
        if c.canonical_url == "https://example.com/about-us"
    )
    reclass = client.patch(
        f"/api/v1/contents/{about_row.id}",
        headers={"X-CSRF-Token": csrf},
        json={"content_type": "custom"},
    )
    assert reclass.status_code == 200
    assert reclass.json()["content_type"] == "custom"
    assert reclass.json()["manual_classification_override"] is True

    page_version[0] = "Version 2 expanded corporate profile and compliance statement."
    s2 = executor.enqueue_scan(site.id, scan_mode="full", dispatch=False)
    r2 = executor.execute_scan(s2.id)
    assert r2.updated_articles == 1
    about_after = memory_repos["contents"].get_by_id(about_row.id)
    assert about_after is not None
    assert about_after.content_type == "custom"  # Scenario 17 preserved!
    assert about_after.manual_classification_override is True
    assert len(memory_repos["contents"].list_revisions(about_row.id)) == 1  # Scenario 22!

    # Scenario 19: Retry Failed URLs once origin stops returning 404
    fail_broken_url[0] = False
    s3 = executor.enqueue_scan(site.id, scan_mode="retry_failed", dispatch=False)
    r3 = executor.execute_scan(s3.id)
    assert r3.status == "completed"
    assert r3.failed_articles == 0
    assert (
        client.get("/api/v1/contents/stats", params={"website_id": site.id}).json()["failed_count"]
        == 0
    )
