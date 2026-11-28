from __future__ import annotations

import httpx

from app.config import Settings
from app.services.publishers.base import BasePublisherAdapter
from app.services.publishers.facebook import FacebookPagesAdapter
from app.services.publishers.google_business import GoogleBusinessProfileAdapter
from app.services.publishers.instagram import InstagramGraphAdapter
from app.services.publishers.linkedin import LinkedInRestAdapter
from app.services.publishers.manual import ManualPublisherAdapter
from app.services.publishers.pinterest import PinterestApiAdapter
from app.services.publishers.threads import ThreadsAdapter
from app.services.publishers.twitter import TwitterApiAdapter

ADAPTER_CLASSES: dict[str, type[BasePublisherAdapter]] = {
    "facebook": FacebookPagesAdapter,
    "instagram": InstagramGraphAdapter,
    "google_business_profile": GoogleBusinessProfileAdapter,
    "threads": ThreadsAdapter,
    "linkedin": LinkedInRestAdapter,
    "pinterest": PinterestApiAdapter,
    "twitter": TwitterApiAdapter,
    "custom_social": ManualPublisherAdapter,
}


class PublisherAdapterRegistry:
    """Factory resolving platform keys to official publishing adapters (injectable for tests)."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        overrides: dict[str, BasePublisherAdapter] | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.transport = transport
        self.overrides = dict(overrides or {})

    def get(
        self,
        platform_key: str,
        *,
        publishing_method: str | None = None,
    ) -> BasePublisherAdapter:
        key = (platform_key or "").strip().lower()
        if publishing_method and publishing_method.strip().lower() == "manual":
            return self.overrides.get("custom_social") or ManualPublisherAdapter(
                timeout_seconds=self.settings.publishing_request_timeout_seconds,
                transport=self.transport,
            )
        if key in self.overrides:
            return self.overrides[key]
        cls = ADAPTER_CLASSES.get(key, ManualPublisherAdapter)
        api_version = None
        if key in {"facebook", "instagram"}:
            api_version = self.settings.meta_graph_api_version
        elif key == "linkedin":
            api_version = self.settings.linkedin_api_version
        return cls(
            timeout_seconds=self.settings.publishing_request_timeout_seconds,
            api_version=api_version,
            transport=self.transport,
        )
