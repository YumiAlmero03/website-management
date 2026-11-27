from __future__ import annotations

import gzip

import httpx
import pytest

from app.config import Settings
from app.services.scanner.browser import PlaywrightFallbackAdapter
from app.services.scanner.exceptions import (
    BrowserUnavailableError,
    DiscoveryError,
    ResponseTooLargeError,
    SSRFBlockedError,
)
from app.services.scanner.html import HtmlDiscoveryAdapter
from app.services.scanner.llms import LlmsTxtDiscoveryAdapter
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.rss import RssDiscoveryAdapter
from app.services.scanner.security import SafeHttpFetcher, validate_outbound_url
from app.services.scanner.sitemap import SitemapDiscoveryAdapter, safe_decompress_gzip
from app.services.scanner.url_normalizer import (
    matches_url_patterns,
    normalize_url,
    validate_url_patterns,
)
from app.services.scanner.wordpress import WordPressDiscoveryAdapter
from tests.conftest import public_dns_resolver


@pytest.mark.parametrize(
    "blocked_url",
    [
        "http://localhost/admin",
        "http://127.0.0.1/secret",
        "http://[::1]/secret",
        "http://10.0.0.5/internal",
        "http://172.16.0.10/internal",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "file:///etc/passwd",
        "ftp://example.com/file.txt",
        "javascript:alert(1)",
        "https://user:pass@example.com/private",
        "https://example.com:8080/nonstandard",
    ],
)
def test_ssrf_blocks_unsafe_urls_schemes_credentials_and_ports(blocked_url: str) -> None:
    with pytest.raises(SSRFBlockedError):
        validate_outbound_url(blocked_url, resolver=public_dns_resolver)


def test_ssrf_blocks_dns_resolving_to_private_ip_and_allows_explicit_trusted_host() -> None:
    with pytest.raises(SSRFBlockedError):
        validate_outbound_url(
            "https://rebind.example.com/",
            resolver=lambda _host, _port: ["10.0.0.99"],
        )

    # Explicit trusted internal host opt-in succeeds only for that host.
    validated = validate_outbound_url(
        "http://staging.internal:8080/feed.xml",
        trusted_internal_hosts={"staging.internal"},
        resolver=lambda _host, _port: ["10.0.0.99"],
    )
    assert validated.is_trusted_internal is True
    assert validated.resolved_ips == ("10.0.0.99",)


def test_ssrf_blocks_redirect_to_localhost_and_enforces_response_size_limit(
    test_settings: Settings,
) -> None:
    def redirect_handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://example.com/start":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/internal"})
        if str(req.url) == "https://example.com/huge":
            return httpx.Response(200, content=b"x" * 100_000)
        return httpx.Response(404)

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(redirect_handler),
    )

    with pytest.raises(SSRFBlockedError):
        fetcher.fetch("https://example.com/start")

    with pytest.raises(ResponseTooLargeError):
        fetcher.fetch("https://example.com/huge", max_bytes=1024)


def test_url_normalization_preserves_meaningful_params_and_pattern_filtering() -> None:
    norm = normalize_url(
        "HTTPS://Example.COM:443/blog/seo-guide/?utm_source=fb&fbclid=123&p=42&page=2#comments"
    )
    assert norm == "https://example.com/blog/seo-guide?p=42&page=2"

    includes = validate_url_patterns(["/blog/*", "/articles/*"])
    excludes = validate_url_patterns(["/tag/*", "/wp-admin/*"])
    assert matches_url_patterns(
        "https://example.com/blog/seo-guide",
        include_patterns=includes,
        exclude_patterns=excludes,
    )
    assert not matches_url_patterns(
        "https://example.com/tag/seo",
        include_patterns=includes,
        exclude_patterns=excludes,
    )
    assert not matches_url_patterns(
        "https://example.com/wp-admin/post.php",
        include_patterns=includes,
        exclude_patterns=excludes,
    )


def test_rss_and_atom_parsing_with_etag_304(test_settings: Settings) -> None:
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>SEO Feed</title>
      <item>
        <title>Technical SEO Checklist</title>
        <link>https://example.com/blog/technical-seo?utm_medium=rss</link>
        <pubDate>Tue, 25 Nov 2026 08:00:00 GMT</pubDate>
        <description>Core technical SEO tips.</description>
      </item>
    </channel></rss>"""

    atom_xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Feed</title>
      <entry>
        <title>Atom Article</title>
        <link href="https://example.com/articles/atom-guide" />
        <id>tag:example.com,2026:atom-guide</id>
        <updated>2026-11-26T05:00:00Z</updated>
        <summary>Atom summary text.</summary>
      </entry>
    </feed>"""

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://example.com/rss.xml":
            if req.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304, headers={"ETag": '"v1"'})
            return httpx.Response(200, text=rss_xml, headers={"ETag": '"v1"'})
        if str(req.url) == "https://example.com/atom.xml":
            return httpx.Response(200, text=atom_xml)
        return httpx.Response(404)

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(handler),
    )
    adapter = RssDiscoveryAdapter(fetcher=fetcher)

    rss_res = adapter.discover(
        domain="example.com", endpoint_url="https://example.com/rss.xml", max_urls=10
    )
    assert len(rss_res.candidates) == 1
    assert rss_res.candidates[0].normalized_url == "https://example.com/blog/technical-seo"
    assert rss_res.etag == '"v1"'

    cached = adapter.discover(
        domain="example.com",
        endpoint_url="https://example.com/rss.xml",
        max_urls=10,
        etag='"v1"',
    )
    assert cached.not_modified is True

    atom_res = adapter.discover(
        domain="example.com", endpoint_url="https://example.com/atom.xml", max_urls=10
    )
    assert len(atom_res.candidates) == 1
    assert atom_res.candidates[0].title == "Atom Article"


def test_sitemap_nested_index_gzip_bomb_cycle_and_xxe_protection(test_settings: Settings) -> None:
    index_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-posts.xml.gz</loc></sitemap>
      <sitemap><loc>https://example.com/sitemap-index.xml</loc></sitemap>
    </sitemapindex>"""

    posts_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.com/blog/sitemap-post-1</loc>
        <lastmod>2026-11-26T00:00:00Z</lastmod>
      </url>
    </urlset>"""

    xxe_xml = """<?xml version="1.0"?>
    <!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
    <urlset><url><loc>&xxe;</loc></url></urlset>"""

    gz_posts = gzip.compress(posts_xml.encode("utf-8"))

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://example.com/sitemap-index.xml":
            return httpx.Response(200, text=index_xml)
        if str(req.url) == "https://example.com/sitemap-posts.xml.gz":
            return httpx.Response(
                200, content=gz_posts, headers={"Content-Type": "application/gzip"}
            )
        if str(req.url) == "https://example.com/xxe.xml":
            return httpx.Response(200, text=xxe_xml)
        return httpx.Response(404)

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(handler),
    )
    adapter = SitemapDiscoveryAdapter(fetcher=fetcher, settings=test_settings)

    result = adapter.discover(
        domain="example.com",
        endpoint_url="https://example.com/sitemap-index.xml",
        max_urls=10,
    )
    assert len(result.candidates) == 1
    assert result.candidates[0].normalized_url == "https://example.com/blog/sitemap-post-1"
    assert any("recursive" in w.lower() for w in result.warnings)

    with pytest.raises(DiscoveryError):
        adapter.discover(
            domain="example.com", endpoint_url="https://example.com/xxe.xml", max_urls=10
        )

    bomb = gzip.compress(b"A" * 200_000)
    with pytest.raises(ResponseTooLargeError):
        safe_decompress_gzip(bomb, max_bytes=10_000)


def test_llms_txt_wordpress_api_html_robots_and_disabled_playwright(
    test_settings: Settings,
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://example.com/llms.txt":
            return httpx.Response(
                200,
                text="# Docs\n- [SEO Architecture](https://example.com/blog/seo-arch)\n",
            )
        if url.startswith("https://example.com/wp-json/wp/v2/posts"):
            return httpx.Response(
                200,
                headers={"X-WP-TotalPages": "1"},
                json=[
                    {
                        "link": "https://example.com/blog/wp-post",
                        "title": {"rendered": "WP &amp; FastAPI Guide"},
                        "excerpt": {"rendered": "<p>Quick intro</p>"},
                        "content": {"rendered": "<p>Full WordPress post body with facts.</p>"},
                        "date_gmt": "2026-11-25T10:00:00",
                        "_embedded": {
                            "author": [{"name": "Jane Editor"}],
                            "wp:featuredmedia": [
                                {"source_url": "https://example.com/img/hero.jpg"}
                            ],
                            "wp:term": [
                                [{"name": "SEO", "taxonomy": "category"}],
                                [{"name": "WordPress", "taxonomy": "post_tag"}],
                            ],
                        },
                    }
                ],
            )
        if url == "https://example.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        if url == "https://example.com/":
            return httpx.Response(
                200,
                text=(
                    "<html><body><nav><a href='/login'>Login</a></nav>"
                    "<article><a href='/blog/html-article'>HTML Article</a></article></body></html>"
                ),
            )
        return httpx.Response(404)

    fetcher = SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=httpx.MockTransport(handler),
    )

    llms_res = LlmsTxtDiscoveryAdapter(fetcher=fetcher).discover(
        domain="example.com", endpoint_url="https://example.com/llms.txt", max_urls=10
    )
    assert len(llms_res.candidates) == 1
    assert llms_res.candidates[0].title == "SEO Architecture"

    wp_res = WordPressDiscoveryAdapter(fetcher=fetcher).discover(
        domain="example.com",
        endpoint_url="https://example.com/wp-json/wp/v2/posts",
        max_urls=10,
    )
    assert len(wp_res.candidates) == 1
    assert wp_res.candidates[0].title == "WP & FastAPI Guide"
    assert wp_res.candidates[0].author == "Jane Editor"
    assert wp_res.candidates[0].categories == ["SEO"]
    assert wp_res.candidates[0].tags == ["WordPress"]

    html_res = HtmlDiscoveryAdapter(fetcher=fetcher).discover(
        domain="example.com", endpoint_url="https://example.com/", max_urls=10
    )
    assert [c.normalized_url for c in html_res.candidates] == [
        "https://example.com/blog/html-article"
    ]

    robots = RobotsPolicyChecker(fetcher=fetcher, user_agent=test_settings.scanner_user_agent)
    assert robots.is_allowed("https://example.com/blog/html-article") is True
    assert robots.is_allowed("https://example.com/private/secret") is False

    browser = PlaywrightFallbackAdapter(settings=test_settings, resolver=public_dns_resolver)
    assert browser.is_available() is False
    with pytest.raises(BrowserUnavailableError):
        browser.render_html("https://example.com/")
