from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class DiscoveredCandidate:
    url: str
    normalized_url: str
    source_method: str
    title: str | None = None
    published_at: datetime | None = None
    modified_at: datetime | None = None
    author: str | None = None
    summary: str | None = None
    featured_image_url: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    raw_html: str | None = None
    raw_markdown: str | None = None
    language: str | None = None


@dataclass
class DiscoveryResult:
    method: str
    candidates: list[DiscoveredCandidate] = field(default_factory=list)
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    warnings: list[str] = field(default_factory=list)


class DiscoveryAdapter(Protocol):
    method_name: str

    def discover(
        self,
        *,
        domain: str,
        endpoint_url: str,
        max_urls: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> DiscoveryResult: ...
