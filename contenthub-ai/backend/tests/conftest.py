from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.dependencies import (
    get_activity_log_repo,
    get_ai_job_dispatcher,
    get_ai_provider_client,
    get_ai_repo,
    get_app_settings,
    get_category_repo,
    get_content_repo,
    get_db_health_checker,
    get_http_fetcher,
    get_keyword_approval_repo,
    get_login_rate_limiter,
    get_media_repo,
    get_publish_job_dispatcher,
    get_publisher_registry,
    get_publishing_repo,
    get_scan_dispatcher,
    get_scan_log_repo,
    get_session_repo,
    get_settings_repo,
    get_social_post_repo,
    get_social_profile_repo,
    get_user_repo,
    get_website_repo,
    get_website_source_repo,
)
from app.core.logging import redact_mapping, redact_text
from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import DatabaseDiagnostic
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.base import ensure_utc, utc_now_naive
from app.models.content_revision import ContentRevision
from app.models.media_asset import MediaAsset
from app.models.session import AdminSession
from app.models.setting import ApplicationSetting
from app.models.user import User
from app.models.website import Website
from app.models.website_category import WebsiteCategory
from app.models.website_content import WebsiteContent
from app.models.website_discovery_source import WebsiteDiscoverySource
from app.models.website_scan_item import WebsiteScanItem
from app.models.website_scan_log import WebsiteScanLog
from app.models.website_url_rule import WebsiteUrlRule
from app.repositories.website_source_repo import hash_endpoint
from app.services.auth_service import AuthService
from app.services.scanner.security import SafeHttpFetcher


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._items: dict[int, User] = {}
        self._seq = 0

    def count_all(self) -> int:
        return len(self._items)

    def get_by_id(self, user_id: int) -> User | None:
        return self._items.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        for user in self._items.values():
            if user.email == normalized:
                return user
        return None

    def create(self, *, email: str, display_name: str, password_hash: str) -> User:
        self._seq += 1
        now = utc_now_naive()
        user = User(
            id=self._seq,
            email=email.strip().lower(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._items[user.id] = user
        return user

    def update_login_metadata(
        self,
        user_id: int,
        *,
        last_login_at: datetime,
        password_hash: str | None = None,
    ) -> User | None:
        user = self._items.get(user_id)
        if user is None:
            return None
        user.last_login_at = last_login_at.replace(tzinfo=None)
        if password_hash is not None:
            user.password_hash = password_hash
        user.updated_at = utc_now_naive()
        return user


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._items: dict[int, AdminSession] = {}
        self._seq = 0

    def create(
        self,
        *,
        user_id: int,
        token_hash: str,
        csrf_token: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AdminSession:
        self._seq += 1
        now = utc_now_naive()
        session = AdminSession(
            id=self._seq,
            user_id=user_id,
            token_hash=token_hash,
            csrf_token=csrf_token,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at.replace(tzinfo=None),
            revoked_at=None,
            last_seen_at=now,
            created_at=now,
        )
        self._items[session.id] = session
        return session

    def get_by_token_hash(self, token_hash: str) -> AdminSession | None:
        for session in self._items.values():
            if session.token_hash == token_hash:
                return session
        return None

    def touch(self, session_id: int, *, seen_at: datetime) -> None:
        session = self._items.get(session_id)
        if session is not None:
            session.last_seen_at = seen_at.replace(tzinfo=None)

    def revoke(self, session_id: int, *, revoked_at: datetime) -> None:
        session = self._items.get(session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = revoked_at.replace(tzinfo=None)

    def count_active(self, *, now: datetime) -> int:
        count = 0
        for session in self._items.values():
            expires_at = ensure_utc(session.expires_at)
            if session.revoked_at is None and expires_at is not None and expires_at > now:
                count += 1
        return count


class InMemorySettingsRepository:
    def __init__(self) -> None:
        self._items: dict[str, ApplicationSetting] = {}
        self._seq = 0

    def list_all(self) -> list[ApplicationSetting]:
        return sorted(self._items.values(), key=lambda row: (row.category, row.setting_key))

    def get_by_key(self, key: str) -> ApplicationSetting | None:
        return self._items.get(key)

    def count_all(self) -> int:
        return len(self._items)

    def upsert(
        self,
        *,
        key: str,
        category: str,
        value_json: Any | None,
        encrypted_value: str | None,
        is_secret: bool,
        description: str,
        updated_by: int | None,
    ) -> ApplicationSetting:
        now = utc_now_naive()
        existing = self._items.get(key)
        if existing is None:
            self._seq += 1
            record = ApplicationSetting(
                id=self._seq,
                setting_key=key,
                category=category,
                value_json=value_json,
                encrypted_value=encrypted_value,
                is_secret=is_secret,
                description=description,
                updated_by=updated_by,
                created_at=now,
                updated_at=now,
            )
            self._items[key] = record
            return record

        existing.category = category
        existing.value_json = value_json
        existing.encrypted_value = encrypted_value
        existing.is_secret = is_secret
        existing.description = description
        existing.updated_by = updated_by
        existing.updated_at = now
        return existing


class InMemoryActivityLogRepository:
    def __init__(self) -> None:
        self._items: list[ActivityLog] = []
        self._seq = 0

    def create(
        self,
        *,
        user_id: int | None,
        actor_type: str,
        category: str,
        action: str,
        level: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> ActivityLog:
        self._seq += 1
        entry = ActivityLog(
            id=self._seq,
            user_id=user_id,
            actor_type=actor_type,
            category=category,
            action=action,
            level=level,
            message=redact_text(message),
            metadata_json=redact_mapping(metadata),
            ip_address=ip_address,
            created_at=utc_now_naive(),
        )
        self._items.append(entry)
        return entry

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        category: str | None = None,
        level: str | None = None,
        search: str | None = None,
    ) -> tuple[list[ActivityLog], int]:
        filtered = list(reversed(self._items))
        if category:
            filtered = [row for row in filtered if row.category == category]
        if level:
            filtered = [row for row in filtered if row.level == level]
        if search:
            term = search.lower()
            filtered = [
                row
                for row in filtered
                if term in row.message.lower()
                or term in row.action.lower()
                or term in row.category.lower()
            ]
        total = len(filtered)
        start = (page - 1) * page_size
        return filtered[start : start + page_size], total

    def count_all(self) -> int:
        return len(self._items)


class InMemoryWebsiteCategoryRepository:
    def __init__(self, *, seed_defaults: bool = True) -> None:
        self._items: dict[int, WebsiteCategory] = {}
        self._seq = 0
        if seed_defaults:
            defaults = [
                ("Sports Web", "sports-web", "Sports news, odds, and analysis publishers", 10),
                ("Casino", "casino", "Online casino, slots, and gaming portals", 20),
                ("Brand", "brand", "Official brand websites and corporate hubs", 30),
                ("Illegal Brand", "illegal-brand", "Flagged or unverified brand domains", 40),
                ("Technology", "technology", "Software, SaaS, and tech publishers", 50),
                ("E-commerce", "e-commerce", "Online stores and product catalogs", 60),
                ("News", "news", "Editorial news and magazine outlets", 70),
                ("Other", "other", "General or uncategorized websites", 80),
            ]
            for name, slug, desc, order in defaults:
                self.create(
                    {
                        "name": name,
                        "slug": slug,
                        "description": desc,
                        "is_archived": False,
                        "sort_order": order,
                    }
                )

    def list_all(self, *, include_archived: bool = False) -> list[WebsiteCategory]:
        rows = list(self._items.values())
        if not include_archived:
            rows = [r for r in rows if not r.is_archived]
        rows.sort(key=lambda r: (r.sort_order, r.name.lower()))
        return rows

    def get_by_id(self, category_id: int) -> WebsiteCategory | None:
        return self._items.get(category_id)

    def get_by_slug(self, slug: str) -> WebsiteCategory | None:
        target = slug.strip().lower()
        for row in self._items.values():
            if row.slug == target:
                return row
        return None

    def get_by_name(self, name: str) -> WebsiteCategory | None:
        target = name.strip().lower()
        for row in self._items.values():
            if row.name.lower() == target:
                return row
        return None

    def count_all(self, *, include_archived: bool = False) -> int:
        if include_archived:
            return len(self._items)
        return sum(1 for r in self._items.values() if not r.is_archived)

    def create(self, data: dict[str, Any]) -> WebsiteCategory:
        self._seq += 1
        now = utc_now_naive()
        cat = WebsiteCategory(id=self._seq, **data, created_at=now, updated_at=now)
        self._items[cat.id] = cat
        return cat

    def update(self, category_id: int, data: dict[str, Any]) -> WebsiteCategory | None:
        cat = self._items.get(category_id)
        if cat is None:
            return None
        for key, value in data.items():
            setattr(cat, key, value)
        cat.updated_at = utc_now_naive()
        return cat

    def delete(self, category_id: int) -> bool:
        return self._items.pop(category_id, None) is not None


class InMemoryWebsiteRepository:
    def __init__(self) -> None:
        self._items: dict[int, Website] = {}
        self._seq = 0

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        category_id: int | None = None,
        status: str | None = None,
        website_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Website], int]:
        rows = sorted(self._items.values(), key=lambda r: r.id, reverse=True)
        if category_id is not None:
            rows = [r for r in rows if r.category_id == category_id]
        if status:
            rows = [r for r in rows if r.status == status]
        if website_type:
            rows = [r for r in rows if r.website_type == website_type]
        if search:
            term = search.strip().lower()
            rows = [
                r
                for r in rows
                if term in r.name.lower()
                or term in (r.brand_name or "").lower()
                or term in r.domain.lower()
            ]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_due_for_scan(self, *, now: datetime) -> list[Website]:
        naive_now = now.replace(tzinfo=None)
        return [
            r
            for r in self._items.values()
            if r.status == "active"
            and r.auto_scan
            and (r.next_scan_at is None or r.next_scan_at <= naive_now)
        ]

    def get_by_id(self, website_id: int) -> Website | None:
        return self._items.get(website_id)

    def get_by_domain(self, domain: str) -> Website | None:
        target = domain.strip().lower()
        for row in self._items.values():
            if row.domain == target:
                return row
        return None

    def count_by_category(self, category_id: int) -> int:
        return sum(1 for r in self._items.values() if r.category_id == category_id)

    def count_all(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        status: str | None = None,
    ) -> int:
        rows = list(self._items.values())
        if website_id is not None:
            rows = [r for r in rows if r.id == website_id]
        if category_id is not None:
            rows = [r for r in rows if r.category_id == category_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return len(rows)

    def count_due(
        self,
        *,
        now: datetime,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        rows = self.list_due_for_scan(now=now)
        if website_id is not None:
            rows = [r for r in rows if r.id == website_id]
        if category_id is not None:
            rows = [r for r in rows if r.category_id == category_id]
        return len(rows)

    def create(self, data: dict[str, Any]) -> Website:
        self._seq += 1
        now = utc_now_naive()
        defaults = {
            "brand_name": data.get("name", "Site"),
            "primary_language": "en",
            "secondary_languages": [],
            "target_keywords": [],
            "restricted_keywords": [],
            "default_hashtags": [],
            "article_url_patterns": [],
            "excluded_url_patterns": [],
            "discovery_method": "auto",
            "single_source_only": False,
            "scan_interval_minutes": 1440,
            "crawl_batch_size": 100,
            "crawl_max_urls_per_run": 1000,
            "initial_scan_completed": False,
            "baseline_mode": "import_existing",
            "auto_scan": True,
            "auto_generate": False,
            "status": "active",
        }
        merged = {**defaults, **data}
        site = Website(id=self._seq, **merged, created_at=now, updated_at=now)
        self._items[site.id] = site
        return site

    def update(self, website_id: int, data: dict[str, Any]) -> Website | None:
        site = self._items.get(website_id)
        if site is None:
            return None
        for key, value in data.items():
            setattr(site, key, value)
        site.updated_at = utc_now_naive()
        return site

    def delete(self, website_id: int) -> bool:
        return self._items.pop(website_id, None) is not None


class InMemoryWebsiteSourceConfigRepository:
    def __init__(self) -> None:
        self._sources: dict[int, WebsiteDiscoverySource] = {}
        self._rules: dict[int, WebsiteUrlRule] = {}
        self._source_seq = 0
        self._rule_seq = 0

    def list_sources(
        self, website_id: int, *, enabled_only: bool = False
    ) -> list[WebsiteDiscoverySource]:
        rows = [s for s in self._sources.values() if s.website_id == website_id]
        if enabled_only:
            rows = [s for s in rows if s.is_enabled]
        rows.sort(key=lambda s: s.id)
        return rows

    def get_source(self, source_id: int) -> WebsiteDiscoverySource | None:
        return self._sources.get(source_id)

    def get_source_by_endpoint(
        self, website_id: int, endpoint_url: str
    ) -> WebsiteDiscoverySource | None:
        ep_hash = hash_endpoint(endpoint_url)
        for src in self._sources.values():
            if src.website_id == website_id and src.endpoint_hash == ep_hash:
                return src
        return None

    def upsert_source(
        self,
        *,
        website_id: int,
        source_type: str,
        endpoint_url: str,
        parent_source_id: int | None = None,
        is_enabled: bool = True,
    ) -> WebsiteDiscoverySource:
        clean_ep = endpoint_url.strip()[:1000]
        existing = self.get_source_by_endpoint(website_id, clean_ep)
        now = utc_now_naive()
        if existing is not None:
            existing.source_type = source_type
            if parent_source_id is not None and existing.parent_source_id is None:
                existing.parent_source_id = parent_source_id
            existing.updated_at = now
            return existing
        self._source_seq += 1
        src = WebsiteDiscoverySource(
            id=self._source_seq,
            website_id=website_id,
            parent_source_id=parent_source_id,
            source_type=source_type,
            endpoint_url=clean_ep,
            endpoint_hash=hash_endpoint(clean_ep),
            is_enabled=is_enabled,
            last_urls_found=0,
            created_at=now,
            updated_at=now,
        )
        self._sources[src.id] = src
        return src

    def update_source(self, source_id: int, data: dict[str, Any]) -> WebsiteDiscoverySource | None:
        src = self._sources.get(source_id)
        if src is None:
            return None
        for key, value in data.items():
            setattr(src, key, value)
        src.updated_at = utc_now_naive()
        return src

    def delete_source(self, source_id: int) -> bool:
        return self._sources.pop(source_id, None) is not None

    def list_rules(self, website_id: int, *, enabled_only: bool = False) -> list[WebsiteUrlRule]:
        rows = [r for r in self._rules.values() if r.website_id == website_id]
        if enabled_only:
            rows = [r for r in rows if r.is_enabled]
        rows.sort(key=lambda r: (r.priority, r.id))
        return rows

    def get_rule(self, rule_id: int) -> WebsiteUrlRule | None:
        return self._rules.get(rule_id)

    def create_rule(self, data: dict[str, Any]) -> WebsiteUrlRule:
        self._rule_seq += 1
        now = utc_now_naive()
        rule = WebsiteUrlRule(id=self._rule_seq, **data, created_at=now, updated_at=now)
        self._rules[rule.id] = rule
        return rule

    def update_rule(self, rule_id: int, data: dict[str, Any]) -> WebsiteUrlRule | None:
        rule = self._rules.get(rule_id)
        if rule is None:
            return None
        for key, value in data.items():
            setattr(rule, key, value)
        rule.updated_at = utc_now_naive()
        return rule

    def delete_rule(self, rule_id: int) -> bool:
        return self._rules.pop(rule_id, None) is not None


class InMemoryContentRepository:
    def __init__(self, website_repo: InMemoryWebsiteRepository) -> None:
        self.website_repo = website_repo
        self._items: dict[int, WebsiteContent] = {}
        self._revisions: list[ContentRevision] = []
        self._seq = 0
        self._rev_seq = 0

    def _matches_category(self, content: WebsiteContent, category_id: int) -> bool:
        site = self.website_repo.get_by_id(content.website_id)
        return site is not None and site.category_id == category_id

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        category_id: int | None = None,
        content_type: str | None = None,
        content_types: list[str] | None = None,
        extraction_status: str | None = None,
        language: str | None = None,
        tag_or_category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        change_filter: str | None = None,
        google_index_status: str | None = None,
        include_excluded: bool = False,
        sort_by: str = "last_discovered_at",
        sort_dir: str = "desc",
    ) -> tuple[list[WebsiteContent], int]:
        rows = list(self._items.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if category_id is not None:
            rows = [r for r in rows if self._matches_category(r, category_id)]
        if not include_excluded and status != "excluded":
            rows = [r for r in rows if not r.is_excluded]
        if content_type:
            rows = [r for r in rows if r.content_type == content_type.strip()]
        elif content_types:
            rows = [r for r in rows if r.content_type in content_types]
        if extraction_status:
            rows = [r for r in rows if r.extraction_status == extraction_status.strip()]
        if language:
            rows = [r for r in rows if (r.language or "") == language.strip()]
        if tag_or_category:
            needle = tag_or_category.strip().lower()
            rows = [
                r
                for r in rows
                if any(str(c).lower() == needle for c in (r.categories or []))
                or any(str(t).lower() == needle for t in (r.tags or []))
            ]
        if status:
            rows = [r for r in rows if r.status == status.strip()]
        if change_filter == "updated":
            rows = [r for r in rows if r.status == "updated"]
        elif change_filter == "new":
            rows = [r for r in rows if r.status in {"discovered", "extracted", "optimized"}]
        if google_index_status:
            if google_index_status == "not_indexed":
                rows = [
                    r
                    for r in rows
                    if getattr(r, "google_index_status", "uninspected") != "indexed"
                ]
            else:
                rows = [
                    r
                    for r in rows
                    if getattr(r, "google_index_status", "uninspected") == google_index_status
                ]
        if date_from is not None:
            cutoff = date_from.replace(tzinfo=None)
            rows = [r for r in rows if r.first_discovered_at >= cutoff]
        if date_to is not None:
            cutoff = date_to.replace(tzinfo=None)
            rows = [r for r in rows if r.first_discovered_at <= cutoff]
        if search:
            term = search.strip().lower()
            rows = [
                r
                for r in rows
                if term in r.title.lower()
                or term in (r.meta_description or "").lower()
                or term in r.canonical_url.lower()
                or term in (r.markdown_content or "").lower()
            ]
        reverse = sort_dir.lower() != "asc"
        if sort_by == "word_count":
            rows.sort(key=lambda r: (r.word_count, r.id), reverse=reverse)
        elif sort_by == "title":
            rows.sort(key=lambda r: (r.title.lower(), r.id), reverse=reverse)
        else:
            rows.sort(key=lambda r: (r.last_discovered_at, r.id), reverse=reverse)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        discovered_since: datetime | None = None,
    ) -> dict[str, int]:
        rows = list(self._items.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if category_id is not None:
            rows = [r for r in rows if self._matches_category(r, category_id)]
        non_excl = [r for r in rows if not r.is_excluded]
        today_cnt = 0
        if discovered_since is not None:
            cutoff = discovered_since.replace(tzinfo=None)
            today_cnt = sum(1 for r in non_excl if r.first_discovered_at >= cutoff)
        return {
            "total_discovered": len(non_excl),
            "total_extracted": sum(1 for r in non_excl if r.extraction_status == "extracted"),
            "homepage_count": sum(1 for r in non_excl if r.content_type == "homepage"),
            "page_count": sum(1 for r in non_excl if r.content_type == "page"),
            "game_page_count": sum(1 for r in non_excl if r.content_type == "game_page"),
            "blog_post_count": sum(1 for r in non_excl if r.content_type == "blog_post"),
            "blog_index_count": sum(1 for r in non_excl if r.content_type == "blog_index"),
            "category_count": sum(1 for r in non_excl if r.content_type == "category"),
            "tag_count": sum(1 for r in non_excl if r.content_type == "tag"),
            "archive_count": sum(1 for r in non_excl if r.content_type == "archive"),
            "custom_count": sum(1 for r in non_excl if r.content_type == "custom"),
            "other_count": sum(
                1 for r in non_excl if r.content_type in {"category", "tag", "archive", "custom"}
            ),
            "pending_count": sum(1 for r in non_excl if r.extraction_status == "pending"),
            "failed_count": sum(1 for r in non_excl if r.extraction_status == "failed"),
            "updated_count": sum(1 for r in non_excl if r.status == "updated"),
            "excluded_count": sum(1 for r in rows if r.is_excluded),
            "discovered_today_count": today_cnt,
        }

    def get_by_id(self, content_id: int) -> WebsiteContent | None:
        return self._items.get(content_id)

    def get_by_website_and_url_hash(self, website_id: int, url_hash: str) -> WebsiteContent | None:
        for row in self._items.values():
            if row.website_id == website_id and row.url_hash == url_hash:
                return row
        return None

    def list_recent_for_website(self, website_id: int, *, limit: int = 50) -> list[WebsiteContent]:
        rows = [r for r in self._items.values() if r.website_id == website_id]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows[:limit]

    def list_pending_for_website(
        self, website_id: int, *, limit: int = 100
    ) -> list[WebsiteContent]:
        rows = [
            r
            for r in self._items.values()
            if r.website_id == website_id and r.extraction_status == "pending" and not r.is_excluded
        ]
        rows.sort(key=lambda r: r.id)
        return rows[:limit]

    def list_failed_for_website(self, website_id: int, *, limit: int = 100) -> list[WebsiteContent]:
        rows = [
            r
            for r in self._items.values()
            if r.website_id == website_id and r.extraction_status == "failed" and not r.is_excluded
        ]
        rows.sort(key=lambda r: r.id)
        return rows[:limit]

    def list_for_website(
        self, website_id: int, *, limit: int | None = None
    ) -> list[WebsiteContent]:
        rows = [r for r in self._items.values() if r.website_id == website_id]
        rows.sort(key=lambda r: r.id)
        return rows[:limit] if limit is not None else rows

    def count_by_website(self, website_id: int) -> int:
        return sum(1 for r in self._items.values() if r.website_id == website_id)

    def count_all(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        content_type: str | None = None,
        extraction_status: str | None = None,
        status: str | None = None,
        discovered_since: datetime | None = None,
    ) -> int:
        rows = [r for r in self._items.values() if not r.is_excluded]
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if category_id is not None:
            rows = [r for r in rows if self._matches_category(r, category_id)]
        if content_type is not None:
            rows = [r for r in rows if r.content_type == content_type]
        if extraction_status is not None:
            rows = [r for r in rows if r.extraction_status == extraction_status]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if discovered_since is not None:
            cutoff = discovered_since.replace(tzinfo=None)
            rows = [r for r in rows if r.first_discovered_at >= cutoff]
        return len(rows)

    def create(self, data: dict[str, Any]) -> WebsiteContent:
        self._seq += 1
        now = utc_now_naive()
        defaults = {
            "content_type": "blog_post",
            "classification_method": "default",
            "manual_classification_override": False,
            "is_excluded": False,
            "categories": [],
            "tags": [],
            "keywords": [],
            "discovery_sources": [],
            "word_count": 0,
            "extraction_status": "extracted",
            "status": "extracted",
            "is_historical_baseline": False,
            "first_discovered_at": now,
            "last_discovered_at": now,
            "last_checked_at": now,
            "created_at": now,
            "updated_at": now,
        }
        merged = {**defaults, **data}
        item = WebsiteContent(id=self._seq, **merged)
        self._items[item.id] = item
        return item

    def update(self, content_id: int, data: dict[str, Any]) -> WebsiteContent | None:
        item = self._items.get(content_id)
        if item is None:
            return None
        for key, value in data.items():
            setattr(item, key, value)
        item.updated_at = utc_now_naive()
        return item

    def list_revisions(self, content_id: int) -> list[ContentRevision]:
        rows = [r for r in self._revisions if r.content_id == content_id]
        rows.sort(key=lambda r: r.revision_number, reverse=True)
        return rows

    def get_next_revision_number(self, content_id: int) -> int:
        revs = self.list_revisions(content_id)
        return (revs[0].revision_number if revs else 0) + 1

    def create_revision(
        self,
        *,
        content_id: int,
        revision_number: int,
        title: str,
        meta_description: str | None,
        markdown_content: str | None,
        content_hash: str,
        content_type: str | None = None,
    ) -> ContentRevision:
        self._rev_seq += 1
        rev = ContentRevision(
            id=self._rev_seq,
            content_id=content_id,
            revision_number=revision_number,
            content_type=content_type,
            title=title,
            meta_description=meta_description,
            markdown_content=markdown_content,
            content_hash=content_hash,
            created_at=utc_now_naive(),
        )
        self._revisions.append(rev)
        return rev


class InMemoryScanLogRepository:
    def __init__(self, website_repo: InMemoryWebsiteRepository) -> None:
        self.website_repo = website_repo
        self._items: dict[int, WebsiteScanLog] = {}
        self._scan_items: dict[int, WebsiteScanItem] = {}
        self._seq = 0
        self._item_seq = 0

    def _matches_category(self, scan: WebsiteScanLog, category_id: int) -> bool:
        site = self.website_repo.get_by_id(scan.website_id)
        return site is not None and site.category_id == category_id

    def get_by_id(self, scan_id: int) -> WebsiteScanLog | None:
        return self._items.get(scan_id)

    def get_active_for_website(self, website_id: int) -> WebsiteScanLog | None:
        rows = [
            s
            for s in self._items.values()
            if s.website_id == website_id and s.status in {"pending", "processing"}
        ]
        rows.sort(key=lambda s: s.id, reverse=True)
        return rows[0] if rows else None

    def get_latest_incomplete_for_website(self, website_id: int) -> WebsiteScanLog | None:
        rows = [
            s
            for s in self._items.values()
            if s.website_id == website_id
            and s.status in {"incomplete", "paused", "partially_completed"}
        ]
        rows.sort(key=lambda s: s.id, reverse=True)
        return rows[0] if rows else None

    def list_for_website(
        self,
        website_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[WebsiteScanLog], int]:
        rows = [s for s in self._items.values() if s.website_id == website_id]
        rows.sort(key=lambda s: s.id, reverse=True)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_recent(
        self,
        *,
        limit: int = 8,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> list[WebsiteScanLog]:
        rows = sorted(self._items.values(), key=lambda s: s.id, reverse=True)
        if website_id is not None:
            rows = [s for s in rows if s.website_id == website_id]
        if category_id is not None:
            rows = [s for s in rows if self._matches_category(s, category_id)]
        return rows[:limit]

    def count_by_status(
        self,
        status: str,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        rows = [s for s in self._items.values() if s.status == status]
        if website_id is not None:
            rows = [s for s in rows if s.website_id == website_id]
        if category_id is not None:
            rows = [s for s in rows if self._matches_category(s, category_id)]
        return len(rows)

    def create(
        self,
        *,
        website_id: int,
        scan_method: str,
        trigger_type: str,
        scan_mode: str = "full",
        status: str = "pending",
    ) -> WebsiteScanLog:
        self._seq += 1
        now = utc_now_naive()
        scan = WebsiteScanLog(
            id=self._seq,
            website_id=website_id,
            scan_method=scan_method,
            scan_mode=scan_mode,
            trigger_type=trigger_type,
            urls_found=0,
            articles_processed=0,
            urls_pending_extraction=0,
            new_articles=0,
            updated_articles=0,
            unchanged_articles=0,
            skipped_articles=0,
            failed_articles=0,
            excluded_count=0,
            homepage_count=0,
            page_count=0,
            blog_post_count=0,
            other_count=0,
            discovered_sitemaps_json=[],
            sources_completed_json=[],
            sources_failed_json=[],
            status=status,
            heartbeat_at=now,
            created_at=now,
        )
        self._items[scan.id] = scan
        return scan

    def claim_pending(self, scan_id: int) -> WebsiteScanLog | None:
        scan = self._items.get(scan_id)
        if scan is None or scan.status != "pending":
            return None
        now = utc_now_naive()
        scan.status = "processing"
        scan.started_at = now
        scan.heartbeat_at = now
        return scan

    def update(self, scan_id: int, data: dict[str, Any]) -> WebsiteScanLog | None:
        scan = self._items.get(scan_id)
        if scan is None:
            return None
        for key, value in data.items():
            setattr(scan, key, value)
        return scan

    def recover_stale_scans(
        self,
        *,
        stale_minutes: int,
        website_id: int | None = None,
    ) -> list[WebsiteScanLog]:
        now = utc_now_naive()
        cutoff = now - timedelta(minutes=stale_minutes)
        recovered: list[WebsiteScanLog] = []
        for scan in self._items.values():
            if website_id is not None and scan.website_id != website_id:
                continue
            if scan.status not in {"pending", "processing"}:
                continue
            ref_time = scan.heartbeat_at or scan.created_at
            if ref_time < cutoff:
                scan.status = "paused" if scan.urls_pending_extraction > 0 else "failed"
                scan.completed_at = now
                scan.error_message = (
                    f"Recovered stale scan after exceeding {stale_minutes} "
                    "minute heartbeat timeout."
                )
                recovered.append(scan)
        return recovered

    def upsert_scan_item(
        self,
        *,
        scan_log_id: int,
        website_id: int,
        url: str,
        normalized_url: str,
        url_hash: str,
        content_type: str,
        discovery_sources: list[str] | None = None,
        discovered_title: str | None = None,
        discovered_published_at: datetime | None = None,
        discovered_modified_at: datetime | None = None,
        status: str = "pending",
        content_id: int | None = None,
        http_status: int | None = None,
        failure_reason: str | None = None,
        error_detail: str | None = None,
    ) -> WebsiteScanItem:
        now = utc_now_naive()
        for existing in self._scan_items.values():
            if existing.scan_log_id == scan_log_id and existing.url_hash == url_hash:
                merged_sources = list(existing.discovery_sources or [])
                for src in discovery_sources or []:
                    if src not in merged_sources:
                        merged_sources.append(src)
                existing.discovery_sources = merged_sources
                existing.content_type = content_type or existing.content_type
                if discovered_title and not existing.discovered_title:
                    existing.discovered_title = discovered_title[:500]
                if content_id is not None:
                    existing.content_id = content_id
                if status:
                    existing.status = status
                if http_status is not None:
                    existing.http_status = http_status
                if failure_reason is not None:
                    existing.failure_reason = failure_reason[:120]
                if error_detail is not None:
                    existing.error_detail = error_detail[:500]
                existing.updated_at = now
                return existing

        self._item_seq += 1
        item = WebsiteScanItem(
            id=self._item_seq,
            scan_log_id=scan_log_id,
            website_id=website_id,
            content_id=content_id,
            url=url[:1000],
            normalized_url=normalized_url[:1000],
            url_hash=url_hash,
            content_type=content_type,
            discovery_sources=list(discovery_sources or []),
            discovered_title=discovered_title[:500] if discovered_title else None,
            discovered_published_at=discovered_published_at,
            discovered_modified_at=discovered_modified_at,
            status=status,
            http_status=http_status,
            failure_reason=failure_reason[:120] if failure_reason else None,
            error_detail=error_detail[:500] if error_detail else None,
            processed_at=now
            if status in {"excluded", "failed", "new", "updated", "unchanged"}
            else None,
            created_at=now,
            updated_at=now,
        )
        self._scan_items[item.id] = item
        return item

    def list_scan_items(
        self,
        scan_log_id: int,
        *,
        status: str | None = None,
        failures_or_excluded_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WebsiteScanItem], int]:
        rows = [r for r in self._scan_items.values() if r.scan_log_id == scan_log_id]
        if status:
            rows = [r for r in rows if r.status == status]
        elif failures_or_excluded_only:
            rows = [r for r in rows if r.status in {"failed", "excluded"}]
        rows.sort(key=lambda r: r.id)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_pending_scan_items(
        self, scan_log_id: int, *, limit: int = 100
    ) -> list[WebsiteScanItem]:
        rows = [
            r
            for r in self._scan_items.values()
            if r.scan_log_id == scan_log_id and r.status == "pending"
        ]
        rows.sort(key=lambda r: r.id)
        return rows[:limit]

    def update_scan_item(self, item_id: int, data: dict[str, Any]) -> WebsiteScanItem | None:
        item = self._scan_items.get(item_id)
        if item is None:
            return None
        for key, value in data.items():
            setattr(item, key, value)
        item.updated_at = utc_now_naive()
        return item

    def count_scan_items_by_status(self, scan_log_id: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._scan_items.values():
            if row.scan_log_id == scan_log_id:
                counts[row.status] = counts.get(row.status, 0) + 1
        return counts


class InMemoryMediaRepository:
    def __init__(self) -> None:
        self._items: dict[int, MediaAsset] = {}
        self._seq = 0

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
    ) -> tuple[list[MediaAsset], int]:
        rows = sorted(self._items.values(), key=lambda r: r.id, reverse=True)
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def get_by_id(self, media_id: int) -> MediaAsset | None:
        return self._items.get(media_id)

    def get_by_checksum(self, checksum: str) -> MediaAsset | None:
        for row in self._items.values():
            if row.checksum == checksum:
                return row
        return None

    def get_by_source_url(
        self, source_url: str, *, website_id: int | None = None
    ) -> MediaAsset | None:
        for row in self._items.values():
            if row.source_url == source_url and (
                website_id is None or row.website_id == website_id
            ):
                return row
        return None

    def create(
        self,
        *,
        website_id: int | None,
        file_name: str,
        file_path: str | None,
        source_url: str | None,
        mime_type: str | None,
        file_size: int | None,
        width: int | None,
        height: int | None,
        alt_text: str | None,
        checksum: str | None,
    ) -> MediaAsset:
        self._seq += 1
        asset = MediaAsset(
            id=self._seq,
            website_id=website_id,
            file_name=file_name,
            file_path=file_path,
            source_url=source_url,
            mime_type=mime_type,
            file_size=file_size,
            width=width,
            height=height,
            alt_text=alt_text,
            checksum=checksum,
            created_at=utc_now_naive(),
        )
        self._items[asset.id] = asset
        return asset


@pytest.fixture()
def test_settings(tmp_path: Any) -> Settings:
    storage_dir = tmp_path / "storage"
    for sub in ("images", "cache", "exports", "backups", "logs"):
        (storage_dir / sub).mkdir(parents=True, exist_ok=True)
    return Settings(
        app_env="test",
        app_secret_key="a" * 64,
        app_encryption_key=Fernet.generate_key().decode("utf-8"),
        session_cookie_secure=False,
        login_rate_limit_max_attempts=3,
        login_rate_limit_window_seconds=300,
        db_user="contenthub_user",
        db_password="test-only-password",
        storage_root=str(storage_dir),
        scanner_crawl_delay_seconds=0.0,
        resource_cpu_warning_percent=99.0,
        resource_cpu_critical_percent=100.0,
        resource_ram_warning_percent=99.0,
        resource_load_avg_threshold=128.0,
    )


@pytest.fixture()
def memory_repos() -> dict[str, Any]:
    from tests.ai_memory_fakes import (
        FakeGeminiProviderClient,
        InMemoryAiRepository,
        InMemorySocialPostRepository,
        InMemorySocialProfileRepository,
    )
    from tests.keyword_approval_fakes import InMemoryKeywordApprovalRepository
    from tests.publishing_fakes import InMemoryPublishingRepository

    website_repo = InMemoryWebsiteRepository()
    content_repo = InMemoryContentRepository(website_repo)
    return {
        "users": InMemoryUserRepository(),
        "sessions": InMemorySessionRepository(),
        "settings": InMemorySettingsRepository(),
        "activities": InMemoryActivityLogRepository(),
        "categories": InMemoryWebsiteCategoryRepository(),
        "websites": website_repo,
        "sources": InMemoryWebsiteSourceConfigRepository(),
        "contents": content_repo,
        "keyword_approvals": InMemoryKeywordApprovalRepository(content_repo),
        "scans": InMemoryScanLogRepository(website_repo),
        "media": InMemoryMediaRepository(),
        "social_profiles": InMemorySocialProfileRepository(),
        "ai": InMemoryAiRepository(),
        "social_posts": InMemorySocialPostRepository(),
        "publishing": InMemoryPublishingRepository(),
        "ai_client": FakeGeminiProviderClient(),
        "rate_limiter": SlidingWindowRateLimiter(max_attempts=3, window_seconds=300),
        "dispatched_scans": [],
        "dispatched_ai_jobs": [],
        "dispatched_publish_jobs": [],
    }


@pytest.fixture()
def db_diagnostic_ok(test_settings: Settings) -> DatabaseDiagnostic:
    return DatabaseDiagnostic(
        connected=True,
        status="ok",
        database_name=test_settings.db_name,
        host=test_settings.db_host,
        port=test_settings.db_port,
        user=test_settings.db_user,
        uses_root_user=False,
        server_version="8.0.45",
        character_set="utf8mb4",
        innodb_available=True,
        latency_ms=1.25,
        pool_size=test_settings.db_pool_size,
        max_overflow=test_settings.db_max_overflow,
        pool_recycle=test_settings.db_pool_recycle,
        error=None,
    )


def public_dns_resolver(hostname: str, _port: int) -> list[str]:
    if hostname in {"example.com", "www.example.com", "blog.example.com", "cdn.example.com"}:
        return ["93.184.216.34"]
    return ["93.184.216.34"]


@pytest.fixture()
def app(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: DatabaseDiagnostic,
) -> FastAPI:
    application = create_app(settings_override=test_settings)
    application.dependency_overrides[get_app_settings] = lambda: test_settings
    application.dependency_overrides[get_user_repo] = lambda: memory_repos["users"]
    application.dependency_overrides[get_session_repo] = lambda: memory_repos["sessions"]
    application.dependency_overrides[get_settings_repo] = lambda: memory_repos["settings"]
    application.dependency_overrides[get_activity_log_repo] = lambda: memory_repos["activities"]
    application.dependency_overrides[get_category_repo] = lambda: memory_repos["categories"]
    application.dependency_overrides[get_website_repo] = lambda: memory_repos["websites"]
    application.dependency_overrides[get_website_source_repo] = lambda: memory_repos["sources"]
    application.dependency_overrides[get_content_repo] = lambda: memory_repos["contents"]
    application.dependency_overrides[get_scan_log_repo] = lambda: memory_repos["scans"]
    application.dependency_overrides[get_media_repo] = lambda: memory_repos["media"]
    application.dependency_overrides[get_social_profile_repo] = lambda: memory_repos[
        "social_profiles"
    ]
    application.dependency_overrides[get_ai_repo] = lambda: memory_repos["ai"]
    application.dependency_overrides[get_social_post_repo] = lambda: memory_repos["social_posts"]
    application.dependency_overrides[get_keyword_approval_repo] = lambda: memory_repos[
        "keyword_approvals"
    ]
    application.dependency_overrides[get_ai_provider_client] = lambda: memory_repos["ai_client"]
    application.dependency_overrides[get_publishing_repo] = lambda: memory_repos["publishing"]
    application.dependency_overrides[get_publish_job_dispatcher] = lambda: (
        lambda job_id: memory_repos["dispatched_publish_jobs"].append(job_id)
    )
    from app.services.publishers.registry import PublisherAdapterRegistry

    application.dependency_overrides[get_publisher_registry] = lambda: PublisherAdapterRegistry(
        settings=test_settings, transport=httpx.MockTransport(lambda _r: httpx.Response(404))
    )
    application.dependency_overrides[get_ai_job_dispatcher] = lambda: (
        lambda job_id: memory_repos["dispatched_ai_jobs"].append(job_id)
    )
    application.dependency_overrides[get_login_rate_limiter] = lambda: memory_repos["rate_limiter"]
    application.dependency_overrides[get_db_health_checker] = lambda: (lambda: db_diagnostic_ok)
    application.dependency_overrides[get_scan_dispatcher] = lambda: (
        lambda scan_id: memory_repos["dispatched_scans"].append(scan_id)
    )
    default_transport = httpx.MockTransport(lambda _req: httpx.Response(404))
    application.dependency_overrides[get_http_fetcher] = lambda: SafeHttpFetcher(
        settings=test_settings,
        resolver=public_dns_resolver,
        transport=default_transport,
    )
    return application


@pytest.fixture()
def seeded_admin(test_settings: Settings, memory_repos: dict[str, Any]) -> dict[str, str]:
    email = "admin@contenthub.local"
    password = "StrongAdmin#Password2026!"
    service = AuthService(
        settings=test_settings,
        user_repo=memory_repos["users"],
        session_repo=memory_repos["sessions"],
        activity_repo=memory_repos["activities"],
        rate_limiter=memory_repos["rate_limiter"],
    )
    service.initialize_admin(email=email, display_name="ContentHub Admin", password=password)
    return {"email": email, "password": password}


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth_client(client: TestClient, seeded_admin: dict[str, str]) -> tuple[TestClient, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_admin["email"], "password": seeded_admin["password"]},
    )
    assert response.status_code == 200
    csrf_token = response.json()["csrf_token"]
    return client, csrf_token
