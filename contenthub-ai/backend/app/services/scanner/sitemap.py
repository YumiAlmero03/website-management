from __future__ import annotations

import gzip
import io
from datetime import UTC, datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from app.config import Settings
from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.exceptions import (
    DiscoveryError,
    ResponseTooLargeError,
    ScannerError,
)
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import normalize_url


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _parse_lastmod(raw: str | None) -> datetime | None:
    if not raw:
        return None
    cleaned = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        try:
            dt = datetime.strptime(cleaned[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=UTC)
        except ValueError:
            return None


def safe_decompress_gzip(payload: bytes, *, max_bytes: int) -> bytes:
    """Decompress gzipped XML safely with a strict output byte ceiling to stop zip bombs."""
    chunks: list[bytes] = []
    total = 0
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as gz:
        while True:
            chunk = gz.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLargeError(
                    f"Decompressed sitemap exceeded maximum allowed size ({max_bytes} bytes)."
                )
            chunks.append(chunk)
    return b"".join(chunks)


class SitemapDiscoveryAdapter:
    """Discovers URLs from XML sitemaps and nested sitemap indexes using defusedxml."""

    method_name = "sitemap"

    def __init__(self, *, fetcher: SafeHttpFetcher, settings: Settings) -> None:
        self.fetcher = fetcher
        self.settings = settings

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
        seen_urls: set[str] = set()
        visited_sitemaps: set[str] = set()
        warnings: list[str] = []
        base_origin = f"https://{domain}"
        files_fetched = [0]
        latest_etag = etag
        latest_modified = last_modified

        def _process_sitemap(sitemap_url: str, depth: int) -> bool:
            if depth > self.settings.scanner_max_sitemap_depth:
                warnings.append(f"Skipped sitemap beyond max depth ({depth}): {sitemap_url}")
                return False
            if files_fetched[0] >= self.settings.scanner_max_sitemap_files:
                warnings.append("Reached maximum sitemap file limit for scan.")
                return False

            try:
                norm_sitemap = normalize_url(sitemap_url, base_url=base_origin)
            except ValueError:
                return False
            if norm_sitemap in visited_sitemaps:
                warnings.append(f"Prevented duplicate/recursive sitemap fetch: {norm_sitemap}")
                return False
            visited_sitemaps.add(norm_sitemap)
            files_fetched[0] += 1

            response = self.fetcher.fetch(
                sitemap_url,
                etag=etag if depth == 0 else None,
                last_modified=last_modified if depth == 0 else None,
                accept="application/xml, text/xml, application/gzip;q=0.9",
            )
            if response.not_modified and depth == 0:
                return True

            if response.status_code != 200:
                if depth == 0:
                    raise DiscoveryError(f"Sitemap returned HTTP {response.status_code}.")
                warnings.append(
                    f"Child sitemap returned HTTP {response.status_code}: {sitemap_url}"
                )
                return False

            if depth == 0:
                nonlocal latest_etag, latest_modified
                latest_etag = response.etag
                latest_modified = response.last_modified

            raw_bytes = response.content
            is_gzip = (
                raw_bytes[:2] == b"\x1f\x8b"
                or sitemap_url.lower().endswith(".gz")
                or "gzip" in response.headers.get("content-type", "").lower()
            )
            if is_gzip:
                try:
                    raw_bytes = safe_decompress_gzip(
                        raw_bytes,
                        max_bytes=self.settings.scanner_max_decompressed_bytes,
                    )
                except OSError as exc:
                    raise DiscoveryError(f"Invalid gzipped sitemap at {sitemap_url}.") from exc

            try:
                root: Element = DefusedET.fromstring(raw_bytes)
            except (DefusedXmlException, DefusedET.ParseError, ValueError) as exc:
                if depth == 0:
                    raise DiscoveryError(f"Invalid or unsafe XML sitemap: {exc}") from exc
                warnings.append(f"Skipped invalid child sitemap {sitemap_url}: {exc}")
                return False

            root_name = _local_tag(root.tag)
            if root_name == "sitemapindex":
                for child in root:
                    if len(candidates) >= max_urls:
                        break
                    if _local_tag(child.tag) != "sitemap":
                        continue
                    loc = self._child_text(child, "loc")
                    if loc:
                        try:
                            _process_sitemap(loc, depth + 1)
                        except (ScannerError, DiscoveryError) as exc:
                            warnings.append(f"Failed child sitemap {loc}: {exc}")
            elif root_name == "urlset":
                for url_node in root:
                    if len(candidates) >= max_urls:
                        break
                    if _local_tag(url_node.tag) != "url":
                        continue
                    loc = self._child_text(url_node, "loc")
                    if not loc:
                        continue
                    try:
                        norm = normalize_url(loc, base_url=base_origin)
                    except ValueError:
                        continue
                    if norm in seen_urls:
                        continue
                    seen_urls.add(norm)
                    lastmod = _parse_lastmod(self._child_text(url_node, "lastmod"))
                    candidates.append(
                        DiscoveredCandidate(
                            url=loc,
                            normalized_url=norm,
                            source_method=self.method_name,
                            modified_at=lastmod,
                        )
                    )
            else:
                if depth == 0:
                    raise DiscoveryError(f"Unexpected sitemap root element: <{root_name}>.")
            return False

        try:
            not_modified = _process_sitemap(endpoint_url, 0)
        except (ScannerError, ResponseTooLargeError) as exc:
            raise DiscoveryError(str(exc)) from exc

        if not_modified:
            return DiscoveryResult(
                method=self.method_name,
                not_modified=True,
                etag=latest_etag,
                last_modified=latest_modified,
            )

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            etag=latest_etag,
            last_modified=latest_modified,
            warnings=warnings,
        )

    @staticmethod
    def _child_text(parent: Element, local_name: str) -> str | None:
        for child in parent:
            if _local_tag(child.tag) == local_name and child.text:
                value = child.text.strip()
                if value:
                    return value
        return None
