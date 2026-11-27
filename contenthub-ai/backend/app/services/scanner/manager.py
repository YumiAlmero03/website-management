from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from app.config import Settings
from app.models.website import Website
from app.models.website_url_rule import WebsiteUrlRule
from app.services.scanner.base import (
    DiscoveredCandidate,
    DiscoveryResult,
    EndpointFetchRecord,
)
from app.services.scanner.browser import PlaywrightFallbackAdapter
from app.services.scanner.classifier import classify_url
from app.services.scanner.discovery import WebsiteAutoDiscovery
from app.services.scanner.exceptions import BrowserUnavailableError, DiscoveryError
from app.services.scanner.html import HtmlDiscoveryAdapter
from app.services.scanner.llms import LlmsTxtDiscoveryAdapter
from app.services.scanner.rest_api import RestApiDiscoveryAdapter
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.rss import RssDiscoveryAdapter
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.sitemap import SitemapDiscoveryAdapter
from app.services.scanner.url_normalizer import is_same_site, normalize_url
from app.services.scanner.wordpress import WordPressDiscoveryAdapter


@dataclass
class SourceEndpointState:
    endpoint_url: str
    source_type: str
    is_enabled: bool = True
    etag: str | None = None
    last_modified_header: str | None = None


@dataclass
class AggregatedDiscoveryOutput:
    method_used: str
    candidates: list[DiscoveredCandidate] = field(default_factory=list)
    excluded_candidates: list[DiscoveredCandidate] = field(default_factory=list)
    total_discovered: int = 0
    skipped_count: int = 0
    discovered_sitemaps: list[str] = field(default_factory=list)
    sources_completed: list[dict[str, object]] = field(default_factory=list)
    sources_failed: list[dict[str, object]] = field(default_factory=list)
    endpoint_records: list[EndpointFetchRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


ProgressCallback = Callable[[str, str], None]


class WebsiteDiscoveryManager:
    """Aggregates multi-source discovery with isolated endpoint caching and classification."""

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
        self.auto_discovery = WebsiteAutoDiscovery(fetcher=fetcher, robots=robots)

    def discover_for_website(
        self,
        website: Website,
        *,
        url_rules: list[WebsiteUrlRule] | None = None,
        source_states: list[SourceEndpointState] | None = None,
        max_urls: int = 20_000,
        scan_mode: str = "full",
        probe_missing_sources: bool = True,
        on_source_start: ProgressCallback | None = None,
    ) -> AggregatedDiscoveryOutput:
        origin = f"https://{website.domain}"
        state_map: dict[str, SourceEndpointState] = {
            st.endpoint_url: st for st in (source_states or [])
        }
        plan = self._build_aggregated_plan(
            website=website,
            origin=origin,
            state_map=state_map,
            probe_missing_sources=probe_missing_sources,
        )

        merged_by_url: dict[str, DiscoveredCandidate] = {}
        sources_completed: list[dict[str, object]] = []
        sources_failed: list[dict[str, object]] = []
        endpoint_records: list[EndpointFetchRecord] = []
        discovered_sitemaps: list[str] = []
        warnings: list[str] = []
        all_304_only = True
        any_succeeded = False

        # Ensure Homepage root '/' is always candidate #1 for aggregated discovery.
        if not website.single_source_only or (website.discovery_method or "auto") == "auto":
            home_norm = normalize_url("/", base_url=origin)
            merged_by_url[home_norm] = DiscoveredCandidate(
                url=f"{origin}/",
                normalized_url=home_norm,
                source_method="homepage",
                discovery_sources=["homepage"],
            )

        endpoint_etag_map: dict[str, tuple[str | None, str | None]] = {
            st.endpoint_url: (st.etag, st.last_modified_header) for st in state_map.values()
        }

        blog_index_urls_to_follow: list[str] = []

        for source_type, endpoint in plan:
            existing_state = state_map.get(endpoint)
            if existing_state is not None and not existing_state.is_enabled:
                continue

            if on_source_start is not None:
                on_source_start(source_type, endpoint)

            ep_etag = existing_state.etag if existing_state else None
            ep_last_mod = existing_state.last_modified_header if existing_state else None
            if scan_mode == "full" and source_type in {"html_links", "homepage"}:
                # In full scan mode, refresh homepage links so newly linked pages appear.
                ep_etag = None
                ep_last_mod = None

            try:
                raw_result = self._invoke_adapter(
                    source_type=source_type,
                    domain=website.domain,
                    endpoint_url=endpoint,
                    max_urls=max_urls,
                    etag=ep_etag,
                    last_modified=ep_last_mod,
                    endpoint_states=endpoint_etag_map if scan_mode == "incremental" else None,
                )
            except (DiscoveryError, BrowserUnavailableError) as exc:
                err_msg = str(exc)
                sources_failed.append(
                    {"source_type": source_type, "endpoint": endpoint, "error": err_msg[:300]}
                )
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=endpoint,
                        source_type=source_type,
                        error=err_msg[:400],
                    )
                )
                warnings.append(f"{source_type} ({endpoint}): {err_msg}")
                if website.single_source_only and (website.discovery_method or "auto") != "auto":
                    raise DiscoveryError(err_msg) from exc
                continue

            any_succeeded = True
            warnings.extend(raw_result.warnings)

            for sm in raw_result.discovered_sitemaps:
                if sm not in discovered_sitemaps:
                    discovered_sitemaps.append(sm)

            if raw_result.endpoint_records:
                endpoint_records.extend(raw_result.endpoint_records)
            else:
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=endpoint,
                        source_type=source_type,
                        status_code=raw_result.status_code
                        or (304 if raw_result.not_modified else 200),
                        not_modified=raw_result.not_modified,
                        etag=raw_result.etag or ep_etag,
                        last_modified=raw_result.last_modified or ep_last_mod,
                        urls_found=len(raw_result.candidates),
                    )
                )

            if raw_result.not_modified:
                sources_completed.append(
                    {
                        "source_type": source_type,
                        "endpoint": endpoint,
                        "status": 304,
                        "urls_found": 0,
                        "note": "304 Not Modified (existing URLs preserved)",
                    }
                )
                continue

            all_304_only = False
            sources_completed.append(
                {
                    "source_type": source_type,
                    "endpoint": endpoint,
                    "status": raw_result.status_code or 200,
                    "urls_found": len(raw_result.candidates),
                }
            )

            for item in raw_result.candidates:
                norm = item.normalized_url
                if norm not in merged_by_url:
                    merged_by_url[norm] = item
                    decision = classify_url(
                        norm,
                        domain=website.domain,
                        custom_rules=url_rules,
                        excluded_patterns=website.excluded_url_patterns,
                    )
                    if (
                        decision.content_type == "blog_index"
                        and not decision.is_excluded
                        and norm not in blog_index_urls_to_follow
                        and len(blog_index_urls_to_follow) < 5
                    ):
                        blog_index_urls_to_follow.append(norm)
                else:
                    self._merge_candidate(merged_by_url[norm], item)

        # Follow up to 5 discovered Blog Index URLs (/blog, /blogs, /news) to capture post links.
        if (
            not website.single_source_only
            and blog_index_urls_to_follow
            and len(merged_by_url) < max_urls
        ):
            for idx_url in blog_index_urls_to_follow:
                if idx_url in {ep for _, ep in plan}:
                    continue
                if on_source_start is not None:
                    on_source_start("blog_index_links", idx_url)
                try:
                    idx_res = self.html.discover(
                        domain=website.domain,
                        endpoint_url=idx_url,
                        max_urls=max_urls,
                        include_nav_links=False,
                        max_pages=3,
                    )
                    for item in idx_res.candidates:
                        item.source_method = "blog_index_links"
                        item.discovery_sources = ["blog_index_links"]
                        if item.normalized_url not in merged_by_url:
                            merged_by_url[item.normalized_url] = item
                        else:
                            self._merge_candidate(merged_by_url[item.normalized_url], item)
                except (DiscoveryError, Exception):
                    continue

        if not any_succeeded and sources_failed and len(merged_by_url) == 0:
            raise DiscoveryError(
                f"All discovery sources failed for {website.domain}. "
                f"Last error: {sources_failed[-1]['error']}"
            )

        included, excluded = self._filter_and_classify_all(
            website=website,
            candidates=list(merged_by_url.values()),
            url_rules=url_rules,
        )

        # Enforce hard discovery cap only above large threshold (no silent 100-URL truncation!)
        if len(included) > max_urls:
            warnings.append(
                f"Discovery reached safety ceiling of {max_urls} URLs ({len(included)} eligible)."
            )
            included = included[:max_urls]

        method_summary = (
            website.discovery_method
            if (website.single_source_only and (website.discovery_method or "auto") != "auto")
            else ("304_cached" if all_304_only and not sources_failed else "aggregated")
        )

        return AggregatedDiscoveryOutput(
            method_used=method_summary,
            candidates=included,
            excluded_candidates=excluded,
            total_discovered=len(merged_by_url),
            skipped_count=len(excluded),
            discovered_sitemaps=discovered_sitemaps,
            sources_completed=sources_completed,
            sources_failed=sources_failed,
            endpoint_records=endpoint_records,
            warnings=warnings,
        )

    def _build_aggregated_plan(
        self,
        *,
        website: Website,
        origin: str,
        state_map: dict[str, SourceEndpointState],
        probe_missing_sources: bool,
    ) -> list[tuple[str, str]]:
        preferred = (website.discovery_method or "auto").strip().lower()
        if website.single_source_only and preferred != "auto":
            return self._single_source_plan(website, origin, preferred)

        plan: list[tuple[str, str]] = []
        seen_eps: set[str] = set()

        def _add(source_type: str, endpoint: str | None) -> None:
            if not endpoint or not endpoint.strip():
                return
            ep = endpoint.strip()
            if ep not in seen_eps:
                seen_eps.add(ep)
                plan.append((source_type, ep))

        # 1. Include any already-persisted enabled discovery sources for this website.
        for st in state_map.values():
            if st.is_enabled and st.source_type != "sitemap":
                _add(st.source_type, st.endpoint_url)
            elif st.is_enabled and st.source_type in {"sitemap", "sitemap_index"}:
                _add("sitemap", st.endpoint_url)

        # 2. Always include website's explicitly configured URLs.
        if website.api_endpoint:
            _add(
                "wordpress" if website.website_type == "wordpress" else "rest_api",
                website.api_endpoint,
            )
        elif preferred == "wordpress":
            _add("wordpress", f"{origin}/wp-json/wp/v2/posts")
        _add("rss", website.rss_url)
        _add("sitemap", website.sitemap_url)
        _add("llms_txt", website.llms_url)

        # 3. Auto-probe robots.txt Sitemap directives & standard sitemaps/RSS/WP/llms.txt so a user
        # who just pasted https://bygame.ph/ gets full multi-source coverage automatically!
        if probe_missing_sources:
            for sm in self.robots.get_sitemap_urls(origin):
                _add("sitemap", sm)
            if not website.sitemap_url:
                probed = self.auto_discovery.discover_sources(website.domain)
                for sm in probed.sitemap_urls:
                    _add("sitemap", sm)
                for rss_u in probed.rss_urls:
                    _add("rss", rss_u)
                if probed.wordpress_api_url:
                    _add("wordpress", probed.wordpress_api_url)
                    _add("wordpress", f"{origin}/wp-json/wp/v2/pages")
                for llms_u in probed.llms_urls:
                    _add("llms_txt", llms_u)

        # 4. Always run HTML internal link discovery on the homepage (unless Playwright explicit)
        _add("html", f"{origin}/")

        # 5. Optional Playwright fallback only when explicitly enabled in settings & site config
        if self.settings.scanner_enable_playwright and preferred == "playwright":
            _add("playwright", f"{origin}/")

        return plan

    def _single_source_plan(
        self, website: Website, origin: str, preferred: str
    ) -> list[tuple[str, str]]:
        if preferred == "rest_api":
            if not website.api_endpoint:
                raise DiscoveryError("Discovery method 'rest_api' requires a configured endpoint.")
            return [("rest_api", website.api_endpoint)]
        if preferred == "wordpress":
            return [("wordpress", website.api_endpoint or f"{origin}/wp-json/wp/v2/posts")]
        if preferred == "rss":
            return [("rss", website.rss_url or f"{origin}/feed/")]
        if preferred == "sitemap":
            return [("sitemap", website.sitemap_url or f"{origin}/sitemap.xml")]
        if preferred == "llms_txt":
            return [("llms_txt", website.llms_url or f"{origin}/llms.txt")]
        if preferred == "html":
            return [("html", f"{origin}/")]
        if preferred == "playwright":
            return [("playwright", f"{origin}/")]
        raise DiscoveryError(f"Unsupported discovery method: '{preferred}'.")

    def _invoke_adapter(
        self,
        *,
        source_type: str,
        domain: str,
        endpoint_url: str,
        max_urls: int,
        etag: str | None,
        last_modified: str | None,
        endpoint_states: dict[str, tuple[str | None, str | None]] | None = None,
    ) -> DiscoveryResult:
        if source_type == "rest_api":
            return self.rest_api.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if source_type in {"wordpress", "wordpress_api"}:
            return self.wordpress.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if source_type in {"rss", "atom"}:
            return self.rss.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if source_type in {"sitemap", "sitemap_index"}:
            return self.sitemap.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
                endpoint_states=endpoint_states,
            )
        if source_type == "llms_txt":
            return self.llms.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
            )
        if source_type in {"html", "html_links"}:
            return self.html.discover(
                domain=domain,
                endpoint_url=endpoint_url,
                max_urls=max_urls,
                etag=etag,
                last_modified=last_modified,
                include_nav_links=True,
                max_pages=10,
            )
        if source_type == "playwright":
            rendered_html = self.browser.render_html(endpoint_url)
            soup = BeautifulSoup(rendered_html, "html.parser")
            candidates: list[DiscoveredCandidate] = []
            seen: set[str] = set()
            self.html._collect_anchor_candidates(
                soup,
                endpoint_url,
                domain,
                candidates,
                seen,
                max_urls,
                include_nav_links=True,
            )
            for item in candidates:
                item.source_method = "playwright"
                item.discovery_sources = ["playwright"]
            return DiscoveryResult(method="playwright", candidates=candidates)

        raise DiscoveryError(f"Unsupported discovery method: '{source_type}'.")

    @staticmethod
    def _merge_candidate(target: DiscoveredCandidate, incoming: DiscoveredCandidate) -> None:
        for src in incoming.discovery_sources:
            if src not in target.discovery_sources:
                target.discovery_sources.append(src)
        if not target.title and incoming.title:
            target.title = incoming.title
        if not target.published_at and incoming.published_at:
            target.published_at = incoming.published_at
        if not target.modified_at and incoming.modified_at:
            target.modified_at = incoming.modified_at
        if not target.author and incoming.author:
            target.author = incoming.author
        if not target.summary and incoming.summary:
            target.summary = incoming.summary
        if not target.featured_image_url and incoming.featured_image_url:
            target.featured_image_url = incoming.featured_image_url
        if not target.raw_html and incoming.raw_html:
            target.raw_html = incoming.raw_html
        if not target.raw_markdown and incoming.raw_markdown:
            target.raw_markdown = incoming.raw_markdown
        for cat in incoming.categories:
            if cat not in target.categories:
                target.categories.append(cat)
        for tag in incoming.tags:
            if tag not in target.tags:
                target.tags.append(tag)
        for jtype in incoming.jsonld_types:
            if jtype not in target.jsonld_types:
                target.jsonld_types.append(jtype)

    def _filter_and_classify_all(
        self,
        *,
        website: Website,
        candidates: list[DiscoveredCandidate],
        url_rules: list[WebsiteUrlRule] | None = None,
    ) -> tuple[list[DiscoveredCandidate], list[DiscoveredCandidate]]:
        kept: list[DiscoveredCandidate] = []
        excluded: list[DiscoveredCandidate] = []
        seen: set[str] = set()

        for item in candidates:
            if item.normalized_url in seen:
                continue
            seen.add(item.normalized_url)

            if not is_same_site(item.normalized_url, website.domain):
                item.exclusion_reason = "cross_domain"
                excluded.append(item)
                continue

            decision = classify_url(
                item.normalized_url,
                domain=website.domain,
                custom_rules=url_rules,
                excluded_patterns=website.excluded_url_patterns,
                include_patterns=website.article_url_patterns,
                jsonld_types=item.jsonld_types,
                og_type=item.og_type,
                source_methods=item.discovery_sources,
            )
            item.content_type = decision.content_type
            item.classification_method = decision.classification_method

            if decision.is_excluded:
                item.exclusion_reason = decision.exclusion_reason or "excluded_pattern"
                excluded.append(item)
                continue

            if not self.robots.is_allowed(item.normalized_url):
                item.exclusion_reason = "robots_txt"
                excluded.append(item)
                continue

            kept.append(item)

        return kept, excluded
