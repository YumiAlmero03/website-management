from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import is_same_site, normalize_url

ARTICLE_JSONLD_TYPES: frozenset[str] = frozenset(
    {"article", "blogposting", "newsarticle", "techarticle", "report"}
)


class HtmlDiscoveryAdapter:
    """Discovers article URLs from standard HTML pages, JSON-LD, Open Graph, and rel=next links."""

    method_name = "html"

    def __init__(self, *, fetcher: SafeHttpFetcher) -> None:
        self.fetcher = fetcher

    def discover(
        self,
        *,
        domain: str,
        endpoint_url: str,
        max_urls: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> DiscoveryResult:
        candidates: list[DiscoveredCandidate] = []
        seen: set[str] = set()
        visited_pages: set[str] = set()
        current_url: str | None = endpoint_url
        page = 0
        latest_etag = etag
        latest_modified = last_modified

        while current_url and len(candidates) < max_urls and page < 5:
            if current_url in visited_pages:
                break
            visited_pages.add(current_url)
            page += 1

            try:
                response = self.fetcher.fetch(
                    current_url,
                    etag=etag if page == 1 else None,
                    last_modified=last_modified if page == 1 else None,
                    accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                )
            except ScannerError as exc:
                if page == 1:
                    raise DiscoveryError(str(exc)) from exc
                break

            if response.not_modified and page == 1:
                return DiscoveryResult(
                    method=self.method_name,
                    not_modified=True,
                    etag=response.etag,
                    last_modified=response.last_modified,
                )

            if response.status_code != 200:
                if page == 1:
                    raise DiscoveryError(f"HTML page returned HTTP {response.status_code}.")
                break

            if page == 1:
                latest_etag = response.etag
                latest_modified = response.last_modified

            soup = BeautifulSoup(response.text, "html.parser")
            self._collect_json_ld_candidates(
                soup, response.final_url, domain, candidates, seen, max_urls
            )
            self._collect_anchor_candidates(
                soup, response.final_url, domain, candidates, seen, max_urls
            )
            current_url = self._find_next_page(soup, response.final_url, domain)

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            etag=latest_etag,
            last_modified=latest_modified,
        )

    def _collect_json_ld_candidates(
        self,
        soup: BeautifulSoup,
        base_url: str,
        domain: str,
        candidates: list[DiscoveredCandidate],
        seen: set[str],
        max_urls: int,
    ) -> None:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for node in self._iter_jsonld_nodes(data):
                if len(candidates) >= max_urls:
                    return
                node_type = str(node.get("@type") or "").lower()
                if node_type not in ARTICLE_JSONLD_TYPES:
                    continue
                raw_url = node.get("url") or (
                    node.get("mainEntityOfPage", {}).get("@id")
                    if isinstance(node.get("mainEntityOfPage"), dict)
                    else node.get("mainEntityOfPage")
                )
                if not isinstance(raw_url, str) or not raw_url.strip():
                    continue
                self._add_candidate(
                    raw_url=raw_url,
                    base_url=base_url,
                    domain=domain,
                    title=str(node.get("headline") or node.get("name") or "").strip() or None,
                    candidates=candidates,
                    seen=seen,
                )

    def _collect_anchor_candidates(
        self,
        soup: BeautifulSoup,
        base_url: str,
        domain: str,
        candidates: list[DiscoveredCandidate],
        seen: set[str],
        max_urls: int,
    ) -> None:
        # Remove obvious chrome so nav/footer/header boilerplate links are ignored.
        for chrome in soup.find_all(["nav", "footer", "aside", "script", "style"]):
            chrome.decompose()

        article_anchors = soup.select("article a[href], main a[href], h2 a[href], h3 a[href]")
        anchors = article_anchors if article_anchors else soup.find_all("a", href=True)

        for anchor in anchors:
            if len(candidates) >= max_urls:
                return
            href = str(anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            text = anchor.get_text(" ", strip=True) or None
            self._add_candidate(
                raw_url=href,
                base_url=base_url,
                domain=domain,
                title=text,
                candidates=candidates,
                seen=seen,
            )

    def _add_candidate(
        self,
        *,
        raw_url: str,
        base_url: str,
        domain: str,
        title: str | None,
        candidates: list[DiscoveredCandidate],
        seen: set[str],
    ) -> None:
        try:
            norm = normalize_url(raw_url, base_url=base_url)
        except ValueError:
            return
        if norm in seen or not is_same_site(norm, domain):
            return
        seen.add(norm)
        candidates.append(
            DiscoveredCandidate(
                url=urljoin(base_url, raw_url),
                normalized_url=norm,
                source_method=self.method_name,
                title=title,
            )
        )

    @staticmethod
    def _find_next_page(soup: BeautifulSoup, base_url: str, domain: str) -> str | None:
        link_next = soup.find("link", rel=lambda v: v and "next" in str(v).lower())
        if link_next and link_next.get("href"):
            candidate = urljoin(base_url, str(link_next["href"]).strip())
            if is_same_site(candidate, domain):
                return candidate
        anchor_next = soup.find("a", rel=lambda v: v and "next" in str(v).lower())
        if anchor_next and anchor_next.get("href"):
            candidate = urljoin(base_url, str(anchor_next["href"]).strip())
            if is_same_site(candidate, domain):
                return candidate
        return None

    @staticmethod
    def _iter_jsonld_nodes(data: Any) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        if isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                for item in data["@graph"]:
                    if isinstance(item, dict):
                        nodes.append(item)
            else:
                nodes.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    nodes.append(item)
        return nodes
