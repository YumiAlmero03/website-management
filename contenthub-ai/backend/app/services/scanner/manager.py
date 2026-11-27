from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.models.website import Website
from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.browser import PlaywrightFallbackAdapter
from app.services.scanner.exceptions import BrowserUnavailableError, DiscoveryError
from app.services.scanner.html import HtmlDiscoveryAdapter
from app.services.scanner.llms import LlmsTxtDiscoveryAdapter
from app.services.scanner.rest_api import RestApiDiscoveryAdapter
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.rss import RssDiscoveryAdapter
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.sitemap import SitemapDiscoveryAdapter
from app.services.scanner.url_normalizer import is_same_site, matches_url_patterns
from app.services.scanner.wordpress import WordPressDiscoveryAdapter

DEFAULT_DISCOVERY_ORDER: tuple[str, ...] = (
    "rest_api",
    "wordpress",
    "rss",
    "sitemap",
    "llms_txt",
    "html",
    "playwright",
)


@dataclass
class FilteredDiscoveryOutput:
    method_used: str
    candidates: list[DiscoveredCandidate] = field(default_factory=list)
    total_discovered: int = 0
    skipped_count: int = 0
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    warnings: list[str] = field(default_factory=list)


class WebsiteDiscoveryManager:
    """Coordinates ordered multi-adapter article URL discovery, robots.txt, and URL filtering."""

    def __init__(
        self,
        *,
        settings: Settings,
        fetcher: SafeHttpFetcher,
        robots: RobotsPolicyChecker,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self.robots = robots
        self.rest_api = RestApiDiscoveryAdapter(fetcher=fetcher)
        self.wordpress = WordPressDiscoveryAdapter(fetcher=fetcher)
        self.rss = RssDiscoveryAdapter(fetcher=fetcher)
        self.sitemap = SitemapDiscoveryAdapter(fetcher=fetcher, settings=settings)
        self.llms = LlmsTxtDiscoveryAdapter(fetcher=fetcher)
        self.html = HtmlDiscoveryAdapter(fetcher=fetcher)
        self.browser = PlaywrightFallbackAdapter(settings=settings, resolver=fetcher.resolver)

    def discover_for_website(
        self,
        website: Website,
        *,
        max_urls: int | None = None,
    ) -> FilteredDiscoveryOutput:
        limit = max_urls or self.settings.scanner_max_urls_per_scan
        preferred = (website.discovery_method or "auto").strip().lower()
        plan = self._build_attempt_plan(website, preferred)

        warnings: list[str] = []
        last_error: str | None = None

        for method, endpoint in plan:
            try:
                raw_result = self._invoke_adapter(
                    method=method,
                    domain=website.domain,
                    endpoint_url=endpoint,
                    max_urls=limit,
                    etag=website.last_etag,
                    last_modified=website.last_modified_header,
                )
            except (DiscoveryError, BrowserUnavailableError) as exc:
                last_error = f"{method}: {exc}"
                warnings.append(last_error)
                if preferred != "auto":
                    raise DiscoveryError(last_error) from exc
                continue

            warnings.extend(raw_result.warnings)
            if raw_result.not_modified:
                return FilteredDiscoveryOutput(
                    method_used=method,
                    not_modified=True,
                    etag=raw_result.etag,
                    last_modified=raw_result.last_modified,
                    warnings=warnings,
                )

            if raw_result.candidates:
                filtered, skipped = self._filter_candidates(website, raw_result.candidates)
                return FilteredDiscoveryOutput(
                    method_used=method,
                    candidates=filtered[:limit],
                    total_discovered=len(raw_result.candidates),
                    skipped_count=skipped,
                    etag=raw_result.etag,
                    last_modified=raw_result.last_modified,
                    warnings=warnings,
                )

            if preferred != "auto":
                return FilteredDiscoveryOutput(
                    method_used=method,
                    candidates=[],
                    total_discovered=0,
                    skipped_count=0,
                    etag=raw_result.etag,
                    last_modified=raw_result.last_modified,
                    warnings=warnings,
                )

        if last_error:
            raise DiscoveryError(
                f"All discovery methods failed for {website.domain}. Last error: {last_error}"
            )

        return FilteredDiscoveryOutput(method_used=preferred, warnings=warnings)

    def _build_attempt_plan(self, website: Website, preferred: str) -> list[tuple[str, str]]:
        origin = f"https://{website.domain}"
        candidates_map: dict[str, str | None] = {
            "rest_api": website.api_endpoint,
            "wordpress": (
                website.api_endpoint
                if website.website_type == "wordpress" and website.api_endpoint
                else (
                    f"{origin}/wp-json/wp/v2/posts" if website.website_type == "wordpress" else None
                )
            ),
            "rss": website.rss_url,
            "sitemap": website.sitemap_url,
            "llms_txt": website.llms_url,
            "html": f"{origin}/",
            "playwright": f"{origin}/" if self.settings.scanner_enable_playwright else None,
        }

        if preferred != "auto":
            target = candidates_map.get(preferred)
            if not target:
                if preferred == "wordpress":
                    target = f"{origin}/wp-json/wp/v2/posts"
                elif preferred == "rss":
                    target = f"{origin}/feed/"
                elif preferred == "sitemap":
                    target = f"{origin}/sitemap.xml"
                elif preferred == "llms_txt":
                    target = f"{origin}/llms.txt"
                elif preferred == "playwright":
                    target = f"{origin}/"
                else:
                    raise DiscoveryError(
                        f"Discovery method '{preferred}' requires a configured endpoint URL."
                    )
            return [(preferred, target)]

        plan: list[tuple[str, str]] = []
        for method in DEFAULT_DISCOVERY_ORDER:
            endpoint = candidates_map.get(method)
            if endpoint:
                plan.append((method, endpoint))
        return plan

    def _invoke_adapter(
        self,
        *,
        method: str,
        domain: str,
        endpoint_url: str,
        max_urls: int,
        etag: str | None,
        last_modified: str | None,
    ) -> DiscoveryResult:
        if method == "rest_api":
            return self.rest_api.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if method == "wordpress":
            return self.wordpress.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if method == "rss":
            return self.rss.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if method == "sitemap":
            return self.sitemap.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if method == "llms_txt":
            return self.llms.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if method == "html":
            return self.html.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if method == "playwright":
            rendered_html = self.browser.render_html(endpoint_url)
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(rendered_html, "html.parser")
            candidates: list[DiscoveredCandidate] = []
            seen: set[str] = set()
            self.html._collect_anchor_candidates(
                soup, endpoint_url, domain, candidates, seen, max_urls
            )
            for item in candidates:
                item.source_method = "playwright"
            return DiscoveryResult(method="playwright", candidates=candidates)

        raise DiscoveryError(f"Unsupported discovery method: '{method}'.")

    def _filter_candidates(
        self,
        website: Website,
        candidates: list[DiscoveredCandidate],
    ) -> tuple[list[DiscoveredCandidate], int]:
        kept: list[DiscoveredCandidate] = []
        seen: set[str] = set()
        skipped = 0

        for item in candidates:
            if item.normalized_url in seen:
                skipped += 1
                continue
            seen.add(item.normalized_url)

            if not is_same_site(item.normalized_url, website.domain):
                skipped += 1
                continue

            if not matches_url_patterns(
                item.normalized_url,
                include_patterns=website.article_url_patterns,
                exclude_patterns=website.excluded_url_patterns,
            ):
                skipped += 1
                continue

            if not self.robots.is_allowed(item.normalized_url):
                skipped += 1
                continue

            kept.append(item)

        return kept, skipped
