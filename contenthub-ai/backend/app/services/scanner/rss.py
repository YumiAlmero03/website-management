from __future__ import annotations

from calendar import timegm
from datetime import UTC, datetime
from typing import Any

import feedparser

from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import normalize_url


def _struct_time_to_utc(parsed_time: Any) -> datetime | None:
    if parsed_time is None:
        return None
    try:
        return datetime.fromtimestamp(timegm(parsed_time), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _extract_entry_image(entry: Any) -> str | None:
    media_content = entry.get("media_content")
    if isinstance(media_content, list):
        for item in media_content:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"]).strip()
    media_thumb = entry.get("media_thumbnail")
    if isinstance(media_thumb, list):
        for item in media_thumb:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"]).strip()
    enclosures = entry.get("enclosures")
    if isinstance(enclosures, list):
        for enc in enclosures:
            if isinstance(enc, dict) and str(enc.get("type", "")).startswith("image/"):
                href = enc.get("href") or enc.get("url")
                if href:
                    return str(href).strip()
    return None


def _find_next_feed_link(parsed_feed: Any) -> str | None:
    links = parsed_feed.feed.get("links", [])
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
                return str(link["href"]).strip()
    return None


class RssDiscoveryAdapter:
    """Discovers articles from RSS 2.0 and Atom feeds using feedparser with HTTP caching."""

    method_name = "rss"

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
        visited_feeds: set[str] = set()
        current_url: str | None = endpoint_url
        page = 0
        latest_etag = etag
        latest_modified = last_modified
        base_origin = f"https://{domain}"
        warnings: list[str] = []

        while current_url and len(candidates) < max_urls and page < 50:
            if current_url in visited_feeds:
                break
            visited_feeds.add(current_url)
            page += 1

            try:
                response = self.fetcher.fetch(
                    current_url,
                    etag=etag if page == 1 else None,
                    last_modified=last_modified if page == 1 else None,
                    accept=(
                        "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9"
                    ),
                )
            except ScannerError as exc:
                if page == 1:
                    raise DiscoveryError(str(exc)) from exc
                warnings.append(f"Feed pagination stopped on page {page}: {exc}")
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
                    raise DiscoveryError(f"RSS/Atom feed returned HTTP {response.status_code}.")
                break

            if page == 1:
                latest_etag = response.etag
                latest_modified = response.last_modified

            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                if page == 1:
                    raise DiscoveryError("Feed content could not be parsed as valid RSS or Atom.")
                break

            for entry in parsed.entries:
                raw_link = entry.get("link") or entry.get("id")
                if not isinstance(raw_link, str) or not raw_link.strip():
                    continue
                if not raw_link.startswith(("http://", "https://", "/")):
                    continue
                try:
                    norm = normalize_url(raw_link, base_url=base_origin)
                except ValueError:
                    continue
                if norm in seen:
                    continue
                seen.add(norm)

                tags_raw = entry.get("tags", [])
                tags: list[str] = []
                if isinstance(tags_raw, list):
                    for tag in tags_raw:
                        term = tag.get("term") if isinstance(tag, dict) else None
                        if isinstance(term, str) and term.strip() and term.strip() not in tags:
                            tags.append(term.strip())

                raw_html: str | None = None
                content_list = entry.get("content")
                if isinstance(content_list, list) and content_list:
                    first = content_list[0]
                    if isinstance(first, dict) and isinstance(first.get("value"), str):
                        raw_html = first["value"]

                candidates.append(
                    DiscoveredCandidate(
                        url=raw_link.strip(),
                        normalized_url=norm,
                        source_method=self.method_name,
                        title=str(entry.get("title") or "").strip() or None,
                        published_at=_struct_time_to_utc(entry.get("published_parsed")),
                        modified_at=_struct_time_to_utc(entry.get("updated_parsed")),
                        author=str(entry.get("author") or "").strip() or None,
                        summary=str(entry.get("summary") or "").strip() or None,
                        featured_image_url=_extract_entry_image(entry),
                        tags=tags,
                        raw_html=raw_html,
                        language=str(parsed.feed.get("language") or "").strip() or None,
                    )
                )
                if len(candidates) >= max_urls:
                    break

            current_url = _find_next_feed_link(parsed)

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            etag=latest_etag,
            last_modified=latest_modified,
            warnings=warnings,
        )
