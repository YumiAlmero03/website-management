from __future__ import annotations

import gzip
import io
from datetime import UTC, datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from app.config import Settings
from app.services.scanner.base import (
    DiscoveredCandidate,
    DiscoveryResult,
    EndpointFetchRecord,
)
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


def decode_sitemap_xml(
    raw_bytes: bytes,
    *,
    sitemap_url: str,
    content_type_header: str = "",
    max_decompressed_bytes: int = 20_971_520,
) -> Element:
    """Detect gzipped or plain XML sitemaps by payload regardless of URL extension (.xml/.php)."""
    is_gzip = (
        raw_bytes[:2] == b"\x1f\x8b"
        or sitemap_url.lower().endswith(".gz")
        or "gzip" in content_type_header.lower()
    )
    payload = raw_bytes
    if is_gzip and raw_bytes[:2] == b"\x1f\x8b":
        try:
            payload = safe_decompress_gzip(raw_bytes, max_bytes=max_decompressed_bytes)
        except OSError as exc:
            raise DiscoveryError(f"Invalid gzipped sitemap at {sitemap_url}.") from exc
    payload = payload.lstrip(b"\xef\xbb\xbf \t\r\n")
    return DefusedET.fromstring(payload)


class SitemapDiscoveryAdapter:
    """Discovers URLs from XML sitemaps, custom .php sitemaps, gzipped XML, and nested indexes."""

    method_name = "sitemap"

    def __init__(self, *, fetcher: SafeHttpFetcher, settings: Settings) -> None:
        self.fetcher = fetcher
        self.settings = settings

    def discover(
        self,
        *,
        domain: str,
        endpoint_url: str,
        max_urls: int = 20_000,
        etag: str | None = None,
        last_modified: str | None = None,
        endpoint_states: dict[str, tuple[str | None, str | None]] | None = None,
    ) -> DiscoveryResult:
        candidates: list[DiscoveredCandidate] = []
        seen_urls: set[str] = set()
        visited_sitemaps: set[str] = set()
        discovered_sitemaps: list[str] = []
        endpoint_records: list[EndpointFetchRecord] = []
        warnings: list[str] = []
        base_origin = f"https://{domain}"
        files_fetched = [0]
        latest_etag = etag
        latest_modified = last_modified
        root_not_modified = False

        def _process_sitemap(sitemap_url: str, depth: int, parent_url: str | None = None) -> None:
            nonlocal root_not_modified, latest_etag, latest_modified
            if depth > self.settings.scanner_max_sitemap_depth:
                warnings.append(f"Skipped sitemap beyond max depth ({depth}): {sitemap_url}")
                return
            if files_fetched[0] >= self.settings.scanner_max_sitemap_files:
                warnings.append("Reached maximum sitemap file limit for scan.")
                return

            try:
                norm_sitemap = normalize_url(sitemap_url, base_url=base_origin)
            except ValueError:
                return
            if norm_sitemap in visited_sitemaps:
                warnings.append(f"Prevented duplicate/recursive sitemap fetch: {norm_sitemap}")
                return
            visited_sitemaps.add(norm_sitemap)
            if norm_sitemap not in discovered_sitemaps:
                discovered_sitemaps.append(norm_sitemap)
            files_fetched[0] += 1

            # Resolve isolated ETag / Last-Modified per individual sitemap endpoint
            ep_etag = etag if depth == 0 else None
            ep_last_mod = last_modified if depth == 0 else None
            if endpoint_states and norm_sitemap in endpoint_states:
                ep_etag, ep_last_mod = endpoint_states[norm_sitemap]
            elif endpoint_states and sitemap_url in endpoint_states:
                ep_etag, ep_last_mod = endpoint_states[sitemap_url]

            response = self.fetcher.fetch(
                sitemap_url,
                etag=ep_etag,
                last_modified=ep_last_mod,
                accept=(
                    "application/xml, text/xml, application/xhtml+xml, "
                    "application/gzip;q=0.9, */*;q=0.5"
                ),
            )
            if response.not_modified:
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=sitemap_url,
                        source_type="sitemap_index" if depth == 0 else "sitemap",
                        status_code=304,
                        not_modified=True,
                        etag=response.etag or ep_etag,
                        last_modified=response.last_modified or ep_last_mod,
                        parent_endpoint_url=parent_url,
                    )
                )
                if depth == 0:
                    root_not_modified = True
                return

            if response.status_code != 200:
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=sitemap_url,
                        source_type="sitemap",
                        status_code=response.status_code,
                        error=f"HTTP {response.status_code}",
                        parent_endpoint_url=parent_url,
                    )
                )
                if depth == 0:
                    raise DiscoveryError(f"Sitemap returned HTTP {response.status_code}.")
                warnings.append(
                    f"Child sitemap returned HTTP {response.status_code}: {sitemap_url}"
                )
                return

            if depth == 0:
                latest_etag = response.etag
                latest_modified = response.last_modified

            try:
                root: Element = decode_sitemap_xml(
                    response.content,
                    sitemap_url=sitemap_url,
                    content_type_header=response.headers.get("content-type", ""),
                    max_decompressed_bytes=self.settings.scanner_max_decompressed_bytes,
                )
            except (DefusedXmlException, DefusedET.ParseError, ValueError, DiscoveryError) as exc:
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=sitemap_url,
                        source_type="sitemap",
                        status_code=response.status_code,
                        error=str(exc)[:400],
                        parent_endpoint_url=parent_url,
                    )
                )
                if depth == 0:
                    raise DiscoveryError(f"Invalid or unsafe XML sitemap: {exc}") from exc
                warnings.append(f"Skipped invalid child sitemap {sitemap_url}: {exc}")
                return

            root_name = _local_tag(root.tag)
            if root_name == "sitemapindex":
                child_locs: list[str] = []
                for child in root:
                    if _local_tag(child.tag) != "sitemap":
                        continue
                    loc = self._child_text(child, "loc")
                    if loc:
                        child_locs.append(loc)
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=sitemap_url,
                        source_type="sitemap_index",
                        status_code=response.status_code,
                        etag=response.etag,
                        last_modified=response.last_modified,
                        urls_found=len(child_locs),
                        parent_endpoint_url=parent_url,
                    )
                )
                for loc in child_locs:
                    try:
                        _process_sitemap(loc, depth + 1, parent_url=sitemap_url)
                    except (ScannerError, DiscoveryError) as exc:
                        warnings.append(f"Failed child sitemap {loc}: {exc}")
            elif root_name == "urlset":
                found_here = 0
                for url_node in root:
                    if len(candidates) >= max_urls:
                        warnings.append(
                            f"Reached safety ceiling ({max_urls} URLs) while reading sitemap."
                        )
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
                    found_here += 1
                    lastmod = _parse_lastmod(self._child_text(url_node, "lastmod"))
                    candidates.append(
                        DiscoveredCandidate(
                            url=loc,
                            normalized_url=norm,
                            source_method=self.method_name,
                            modified_at=lastmod,
                        )
                    )
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=sitemap_url,
                        source_type="sitemap",
                        status_code=response.status_code,
                        etag=response.etag,
                        last_modified=response.last_modified,
                        urls_found=found_here,
                        parent_endpoint_url=parent_url,
                    )
                )
            else:
                endpoint_records.append(
                    EndpointFetchRecord(
                        endpoint_url=sitemap_url,
                        source_type="sitemap",
                        status_code=response.status_code,
                        error=f"Unexpected XML root element <{root_name}>",
                        parent_endpoint_url=parent_url,
                    )
                )
                if depth == 0:
                    raise DiscoveryError(f"Unexpected sitemap root element: <{root_name}>.")

        try:
            _process_sitemap(endpoint_url, 0)
        except (ScannerError, ResponseTooLargeError) as exc:
            raise DiscoveryError(str(exc)) from exc

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            not_modified=root_not_modified and not candidates,
            etag=latest_etag,
            last_modified=latest_modified,
            status_code=304 if root_not_modified else 200,
            discovered_sitemaps=discovered_sitemaps,
            endpoint_records=endpoint_records,
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
