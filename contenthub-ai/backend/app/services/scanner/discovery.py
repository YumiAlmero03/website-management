from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.scanner.exceptions import ScannerError
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher


@dataclass
class WebsiteConnectivityResult:
    reachable: bool
    status_code: int | None
    final_url: str | None
    title: str | None
    detected_website_type: str | None
    error: str | None = None


@dataclass
class WebsiteSourcesDiscoveryResult:
    reachable: bool
    homepage_url: str
    rss_urls: list[str] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)
    llms_urls: list[str] = field(default_factory=list)
    wordpress_api_url: str | None = None
    recommended_method: str = "html"
    notes: list[str] = field(default_factory=list)


class WebsiteAutoDiscovery:
    """Probes website connectivity and auto-discovers WordPress API, RSS, sitemaps, and llms.txt."""

    def __init__(
        self,
        *,
        fetcher: SafeHttpFetcher,
        robots: RobotsPolicyChecker,
    ) -> None:
        self.fetcher = fetcher
        self.robots = robots

    def test_connectivity(self, domain: str) -> WebsiteConnectivityResult:
        homepage = f"https://{domain}/"
        try:
            response = self.fetcher.fetch(homepage, accept="text/html,*/*;q=0.8", max_retries=1)
        except ScannerError as exc:
            return WebsiteConnectivityResult(
                reachable=False,
                status_code=None,
                final_url=None,
                title=None,
                detected_website_type=None,
                error=str(exc),
            )

        title: str | None = None
        detected_type: str | None = None
        if response.status_code == 200 and response.content:
            soup = BeautifulSoup(response.text, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()[:200]
            detected_type = self._detect_cms(soup, response.text, response.headers)

        return WebsiteConnectivityResult(
            reachable=200 <= response.status_code < 400,
            status_code=response.status_code,
            final_url=response.final_url,
            title=title,
            detected_website_type=detected_type,
            error=None if response.status_code < 400 else f"Received HTTP {response.status_code}.",
        )

    def discover_sources(self, domain: str) -> WebsiteSourcesDiscoveryResult:
        origin = f"https://{domain}"
        result = WebsiteSourcesDiscoveryResult(reachable=False, homepage_url=f"{origin}/")

        try:
            home_resp = self.fetcher.fetch(
                f"{origin}/", accept="text/html,*/*;q=0.8", max_retries=1
            )
        except ScannerError as exc:
            result.notes.append(f"Homepage check failed: {exc}")
            return result

        result.reachable = 200 <= home_resp.status_code < 400
        if home_resp.status_code == 200:
            soup = BeautifulSoup(home_resp.text, "html.parser")
            for link in soup.find_all("link", rel=lambda v: v and "alternate" in str(v).lower()):
                link_type = str(link.get("type") or "").lower()
                href = str(link.get("href") or "").strip()
                if not href:
                    continue
                if "rss+xml" in link_type or "atom+xml" in link_type:
                    full_feed = urljoin(home_resp.final_url, href)
                    if full_feed not in result.rss_urls:
                        result.rss_urls.append(full_feed)

        # Check WordPress public REST API endpoint.
        wp_url = f"{origin}/wp-json/wp/v2/posts?per_page=1"
        if self._probe_ok(wp_url, expected_substrings=("[", "link"), accept="application/json"):
            result.wordpress_api_url = f"{origin}/wp-json/wp/v2/posts"

        # Check common RSS/Atom feed locations if homepage did not advertise any.
        if not result.rss_urls:
            for path in ("/feed/", "/rss.xml", "/atom.xml", "/feed.xml"):
                probe = f"{origin}{path}"
                if self._probe_ok(probe, expected_substrings=("<rss", "<feed", "<channel")):
                    result.rss_urls.append(probe)
                    break

        # Check robots.txt Sitemap directives plus common sitemap locations.
        for sm in self.robots.get_sitemap_urls(origin):
            if sm not in result.sitemap_urls:
                result.sitemap_urls.append(sm)
        if not result.sitemap_urls:
            for path in ("/sitemap.xml", "/sitemap_index.xml"):
                probe = f"{origin}{path}"
                if self._probe_ok(probe, expected_substrings=("<urlset", "<sitemapindex")):
                    result.sitemap_urls.append(probe)
                    break

        # Check /llms.txt supplemental discovery source.
        llms_probe = f"{origin}/llms.txt"
        if self._probe_ok(llms_probe, expected_substrings=("http", "#")):
            result.llms_urls.append(llms_probe)

        if result.wordpress_api_url:
            result.recommended_method = "wordpress"
        elif result.rss_urls:
            result.recommended_method = "rss"
        elif result.sitemap_urls:
            result.recommended_method = "sitemap"
        elif result.llms_urls:
            result.recommended_method = "llms_txt"
        else:
            result.recommended_method = "html"

        return result

    def _probe_ok(
        self,
        url: str,
        *,
        expected_substrings: tuple[str, ...],
        accept: str = "*/*",
    ) -> bool:
        try:
            resp = self.fetcher.fetch(url, accept=accept, max_retries=0)
        except ScannerError:
            return False
        if resp.status_code != 200 or not resp.content:
            return False
        snippet = resp.text[:4096].lower()
        return any(token.lower() in snippet for token in expected_substrings)

    @staticmethod
    def _detect_cms(soup: BeautifulSoup, body: str, headers: dict[str, str]) -> str:
        generator = soup.find("meta", attrs={"name": "generator"})
        gen_val = str(generator.get("content") or "").lower() if generator else ""
        lowered = body[:10000].lower()
        if "wordpress" in gen_val or "/wp-content/" in lowered or "/wp-json/" in lowered:
            return "wordpress"
        if "__nuxt" in lowered or "/_nuxt/" in lowered:
            return "nuxt"
        if "__next_data__" in lowered or "/_next/" in lowered:
            return "nextjs"
        if "php" in headers.get("x-powered-by", "").lower():
            return "custom_php"
        return "static_html"
