from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import normalize_url


def _parse_wp_datetime(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _strip_html(raw: str | None) -> str | None:
    if not raw:
        return None
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return html.unescape(text).strip() or None


def _build_wp_page_url(base_endpoint: str, page: int, per_page: int) -> str:
    parsed = urlparse(base_endpoint)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["per_page"] = str(per_page)
    params["page"] = str(page)
    params["_embed"] = "1"
    return urlunparse(parsed._replace(query=urlencode(params)))


class WordPressDiscoveryAdapter:
    """Discovers public WordPress posts via /wp-json/wp/v2/posts without requiring credentials."""

    method_name = "wordpress"

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
        per_page = min(20, max(1, max_urls))
        candidates: list[DiscoveredCandidate] = []
        seen: set[str] = set()
        page = 1
        total_pages = 1
        latest_etag = etag
        latest_modified = last_modified
        base_origin = f"https://{domain}"

        while len(candidates) < max_urls and page <= total_pages and page <= 10:
            page_url = _build_wp_page_url(endpoint_url, page, per_page)
            try:
                response = self.fetcher.fetch(
                    page_url,
                    etag=etag if page == 1 else None,
                    last_modified=last_modified if page == 1 else None,
                    accept="application/json",
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
                    raise DiscoveryError(
                        f"WordPress REST API returned HTTP {response.status_code}."
                    )
                break

            if page == 1:
                latest_etag = response.etag
                latest_modified = response.last_modified
                raw_total_pages = response.headers.get("x-wp-totalpages", "1")
                if raw_total_pages.isdigit():
                    total_pages = max(1, int(raw_total_pages))

            try:
                posts = json.loads(response.text)
            except json.JSONDecodeError as exc:
                raise DiscoveryError("WordPress endpoint did not return valid JSON.") from exc

            if not isinstance(posts, list) or not posts:
                break

            for post in posts:
                if not isinstance(post, dict):
                    continue
                raw_link = post.get("link")
                if not isinstance(raw_link, str) or not raw_link.strip():
                    continue
                try:
                    norm = normalize_url(raw_link, base_url=base_origin)
                except ValueError:
                    continue
                if norm in seen:
                    continue
                seen.add(norm)

                title_obj = post.get("title")
                title_raw = title_obj.get("rendered") if isinstance(title_obj, dict) else title_obj
                title = _strip_html(str(title_raw)) if title_raw else None

                excerpt_obj = post.get("excerpt")
                excerpt_raw = excerpt_obj.get("rendered") if isinstance(excerpt_obj, dict) else None
                summary = _strip_html(excerpt_raw)

                content_obj = post.get("content")
                content_html = (
                    content_obj.get("rendered")
                    if isinstance(content_obj, dict)
                    and isinstance(content_obj.get("rendered"), str)
                    else None
                )

                embedded = post.get("_embedded") if isinstance(post.get("_embedded"), dict) else {}
                author_name = self._extract_author(embedded)
                featured_image = self._extract_featured_media(embedded)
                categories, tags = self._extract_terms(embedded)

                candidates.append(
                    DiscoveredCandidate(
                        url=raw_link.strip(),
                        normalized_url=norm,
                        source_method=self.method_name,
                        title=title,
                        published_at=_parse_wp_datetime(post.get("date_gmt") or post.get("date")),
                        modified_at=_parse_wp_datetime(
                            post.get("modified_gmt") or post.get("modified")
                        ),
                        author=author_name,
                        summary=summary,
                        featured_image_url=featured_image,
                        categories=categories,
                        tags=tags,
                        raw_html=content_html,
                    )
                )
                if len(candidates) >= max_urls:
                    break

            page += 1

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            etag=latest_etag,
            last_modified=latest_modified,
        )

    @staticmethod
    def _extract_author(embedded: dict[str, Any]) -> str | None:
        authors = embedded.get("author")
        if isinstance(authors, list) and authors and isinstance(authors[0], dict):
            name = authors[0].get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return None

    @staticmethod
    def _extract_featured_media(embedded: dict[str, Any]) -> str | None:
        media = embedded.get("wp:featuredmedia")
        if isinstance(media, list) and media and isinstance(media[0], dict):
            source_url = media[0].get("source_url")
            if isinstance(source_url, str) and source_url.strip():
                return source_url.strip()
        return None

    @staticmethod
    def _extract_terms(embedded: dict[str, Any]) -> tuple[list[str], list[str]]:
        categories: list[str] = []
        tags: list[str] = []
        term_groups = embedded.get("wp:term")
        if not isinstance(term_groups, list):
            return categories, tags
        for group in term_groups:
            if not isinstance(group, list):
                continue
            for term in group:
                if not isinstance(term, dict):
                    continue
                name = str(term.get("name") or "").strip()
                taxonomy = str(term.get("taxonomy") or "").strip().lower()
                if not name:
                    continue
                if taxonomy == "category" and name not in categories:
                    categories.append(name)
                elif taxonomy == "post_tag" and name not in tags:
                    tags.append(name)
        return categories, tags
