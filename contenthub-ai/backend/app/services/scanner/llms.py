from __future__ import annotations

import re

from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import normalize_url

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s<>)\]]+)")


class LlmsTxtDiscoveryAdapter:
    """Supplemental discovery adapter parsing /llms.txt and linked Markdown resources."""

    method_name = "llms_txt"

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
        try:
            response = self.fetcher.fetch(
                endpoint_url,
                etag=etag,
                last_modified=last_modified,
                accept="text/plain, text/markdown;q=0.9, */*;q=0.5",
            )
        except ScannerError as exc:
            raise DiscoveryError(str(exc)) from exc

        if response.not_modified:
            return DiscoveryResult(
                method=self.method_name,
                not_modified=True,
                etag=response.etag,
                last_modified=response.last_modified,
            )

        if response.status_code != 200:
            raise DiscoveryError(f"llms.txt returned HTTP {response.status_code}.")

        base_origin = f"https://{domain}"
        candidates: list[DiscoveredCandidate] = []
        seen: set[str] = set()

        for line in response.text.splitlines():
            if len(candidates) >= max_urls:
                break
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            matched = False
            for match in _MD_LINK_RE.finditer(stripped):
                matched = True
                title = match.group(1).strip()
                raw_url = match.group(2).strip()
                self._append_candidate(
                    candidates=candidates,
                    seen=seen,
                    raw_url=raw_url,
                    base_origin=base_origin,
                    title=title,
                    max_urls=max_urls,
                )
            if not matched:
                for match in _BARE_URL_RE.finditer(stripped):
                    raw_url = match.group(1).rstrip(".,;:")
                    self._append_candidate(
                        candidates=candidates,
                        seen=seen,
                        raw_url=raw_url,
                        base_origin=base_origin,
                        title=None,
                        max_urls=max_urls,
                    )

        return DiscoveryResult(
            method=self.method_name,
            candidates=candidates,
            etag=response.etag,
            last_modified=response.last_modified,
            warnings=[
                "llms.txt is a supplemental discovery source and may omit "
                "articles or publication dates."
            ],
        )

    def _append_candidate(
        self,
        *,
        candidates: list[DiscoveredCandidate],
        seen: set[str],
        raw_url: str,
        base_origin: str,
        title: str | None,
        max_urls: int,
    ) -> None:
        if len(candidates) >= max_urls:
            return
        try:
            norm = normalize_url(raw_url, base_url=base_origin)
        except ValueError:
            return
        if norm in seen or norm.rstrip("/").endswith("/llms.txt"):
            return
        seen.add(norm)
        candidates.append(
            DiscoveredCandidate(
                url=raw_url,
                normalized_url=norm,
                source_method=self.method_name,
                title=title or None,
            )
        )
