from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class DiscoveredCandidate:
    url: str
    normalized_url: str
    source_method: str
    discovery_sources: list[str] = field(default_factory=list)
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
    jsonld_types: list[str] = field(default_factory=list)
    og_type: str | None = None
    content_type: str | None = None
    classification_method: str | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.source_method and self.source_method not in self.discovery_sources:
            self.discovery_sources.append(self.source_method)


@dataclass
class EndpointFetchRecord:
    endpoint_url: str
    source_type: str
    status_code: int | None = None
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    urls_found: int = 0
    error: str | None = None
    parent_endpoint_url: str | None = None


@dataclass
class DiscoveryResult:
    method: str
    candidates: list[DiscoveredCandidate] = field(default_factory=list)
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    status_code: int | None = None
    discovered_sitemaps: list[str] = field(default_factory=list)
    endpoint_records: list[EndpointFetchRecord] = field(default_factory=list)
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
        extra: dict[str, Any] | None = None,
    ) -> DiscoveryResult: ...
