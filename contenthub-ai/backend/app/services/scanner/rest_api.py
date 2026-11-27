from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import normalize_url


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _with_query_params(url: str, extra: dict[str, str]) -> str:
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update(extra)
    return urlunparse(parsed._replace(query=urlencode(params)))


class RestApiDiscoveryAdapter:
    """Discovers articles from a configured generic JSON REST API endpoint."""

    method_name = "rest_api"

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
        next_url: str | None = endpoint_url
        page_count = 0
        latest_etag = etag
        latest_modified = last_modified

        while next_url and len(candidates) < max_urls and page_count < 100:
            page_count += 1
            try:
                response = self.fetcher.fetch(
                    next_url,
                    etag=etag if page_count == 1 else None,
                    last_modified=last_modified if page_count == 1 else None,
                    accept="application/json",
                )
            except ScannerError as exc:
                if page_count == 1:
                    raise DiscoveryError(str(exc)) from exc
                break

            if response.not_modified and page_count == 1:
                return DiscoveryResult(
                    method=self.method_name,
                    not_modified=True,
                    etag=response.etag,
                    last_modified=response.last_modified,
                )

            if response.status_code != 200:
                if page_count == 1:
                    raise DiscoveryError(f"REST API returned HTTP {response.status_code}.")
                break

            if page_count == 1:
                latest_etag = response.etag
                latest_modified = response.last_modified

            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError as exc:
                raise DiscoveryError("Configured REST API did not return valid JSON.") from exc

            items: list[Any]
            next_candidate_url: str | None = None
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = (
                    payload.get("items")
                    or payload.get("articles")
                    or payload.get("posts")
                    or payload.get("data")
                    or []
                )
                if not isinstance(items, list):
                    items = []
                raw_next = payload.get("next") or payload.get("next_url")
                if isinstance(raw_next, str) and raw_next.strip():
                    next_candidate_url = raw_next.strip()
            else:
                items = []

            if not items:
                break

            base_origin = f"https://{domain}"
            for item in items:
                if not isinstance(item, dict):
                    continue
                raw_url = (
                    item.get("canonical_url")
                    or item.get("url")
                    or item.get("link")
                    or item.get("permalink")
                )
                if not isinstance(raw_url, str) or not raw_url.strip():
                    continue
                try:
                    norm = normalize_url(raw_url, base_url=base_origin)
                except ValueError:
                    continue
                if norm in seen:
                    continue
                seen.add(norm)

                raw_title = item.get("title")
                title = (
                    raw_title.get("rendered")
                    if isinstance(raw_title, dict)
                    else (str(raw_title).strip() if raw_title else None)
                )
                raw_cats = item.get("categories")
                raw_tags = item.get("tags")
                candidates.append(
                    DiscoveredCandidate(
                        url=raw_url.strip(),
                        normalized_url=norm,
                        source_method=self.method_name,
                        title=title,
                        published_at=_parse_iso_datetime(
                            item.get("published_at") or item.get("date") or item.get("created_at")
                        ),
                        modified_at=_parse_iso_datetime(
                            item.get("updated_at") or item.get("modified")
                        ),
                        author=str(item["author"]).strip()
                        if isinstance(item.get("author"), str)
                        else None,
                        summary=str(
                            item.get("meta_description") or item.get("excerpt") or ""
                        ).strip()
                        or None,
                        featured_image_url=str(
                            item.get("featured_image") or item.get("image") or ""
                        ).strip()
                        or None,
                        categories=[str(c) for c in raw_cats] if isinstance(raw_cats, list) else [],
                        tags=[str(t) for t in raw_tags] if isinstance(raw_tags, list) else [],
                        raw_html=item.get("content_html")
                        if isinstance(item.get("content_html"), str)
                        else None,
                        raw_markdown=item.get("markdown")
                        if isinstance(item.get("markdown"), str)
                        else None,
                        language=str(item["language"]).strip()
                        if isinstance(item.get("language"), str)
                        else None,
                    )
                )
                if len(candidates) >= max_urls:
                    break

            next_url = next_candidate_url
            if next_url is None and isinstance(payload, dict) and payload.get("has_more") is True:
                next_url = _with_query_params(endpoint_url, {"page": str(page_count + 1)})

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            etag=latest_etag,
            last_modified=latest_modified,
        )
