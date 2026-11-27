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
    get_app_settings,
    get_article_repo,
    get_brand_repo,
    get_db_health_checker,
    get_http_fetcher,
    get_login_rate_limiter,
    get_media_repo,
    get_scan_dispatcher,
    get_scan_log_repo,
    get_session_repo,
    get_settings_repo,
    get_user_repo,
    get_website_repo,
)
from app.core.logging import redact_mapping, redact_text
from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import DatabaseDiagnostic
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.base import ensure_utc, utc_now_naive
from app.models.brand import Brand
from app.models.media_asset import MediaAsset
from app.models.session import AdminSession
from app.models.setting import ApplicationSetting
from app.models.source_article import SourceArticle
from app.models.source_article_revision import SourceArticleRevision
from app.models.user import User
from app.models.website import Website
from app.models.website_scan_log import WebsiteScanLog
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


class InMemoryBrandRepository:
    def __init__(self) -> None:
        self._items: dict[int, Brand] = {}
        self._seq = 0

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
        language: str | None = None,
    ) -> tuple[list[Brand], int]:
        rows = sorted(self._items.values(), key=lambda r: r.id, reverse=True)
        if is_active is not None:
            rows = [r for r in rows if r.is_active == is_active]
        if language:
            rows = [r for r in rows if r.primary_language == language.strip()]
        if search:
            term = search.strip().lower()
            rows = [
                r
                for r in rows
                if term in r.name.lower()
                or term in r.slug.lower()
                or term in (r.description or "").lower()
                or term in (r.target_country or "").lower()
            ]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_all(self) -> list[Brand]:
        return sorted(self._items.values(), key=lambda r: r.name.lower())

    def get_by_id(self, brand_id: int) -> Brand | None:
        return self._items.get(brand_id)

    def get_by_slug(self, slug: str) -> Brand | None:
        target = slug.strip().lower()
        for row in self._items.values():
            if row.slug == target:
                return row
        return None

    def count_all(self, *, is_active: bool | None = None) -> int:
        if is_active is None:
            return len(self._items)
        return sum(1 for r in self._items.values() if r.is_active == is_active)

    def create(self, data: dict[str, Any]) -> Brand:
        self._seq += 1
        now = utc_now_naive()
        brand = Brand(id=self._seq, **data, created_at=now, updated_at=now)
        self._items[brand.id] = brand
        return brand

    def update(self, brand_id: int, data: dict[str, Any]) -> Brand | None:
        brand = self._items.get(brand_id)
        if brand is None:
            return None
        for key, value in data.items():
            setattr(brand, key, value)
        brand.updated_at = utc_now_naive()
        return brand

    def delete(self, brand_id: int) -> bool:
        return self._items.pop(brand_id, None) is not None


class InMemoryWebsiteRepository:
    def __init__(self) -> None:
        self._items: dict[int, Website] = {}
        self._seq = 0

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
        status: str | None = None,
        website_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Website], int]:
        rows = sorted(self._items.values(), key=lambda r: r.id, reverse=True)
        if brand_id is not None:
            rows = [r for r in rows if r.brand_id == brand_id]
        if status:
            rows = [r for r in rows if r.status == status]
        if website_type:
            rows = [r for r in rows if r.website_type == website_type]
        if search:
            term = search.strip().lower()
            rows = [r for r in rows if term in r.name.lower() or term in r.domain.lower()]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_by_brand(self, brand_id: int) -> list[Website]:
        return [r for r in self._items.values() if r.brand_id == brand_id]

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

    def get_by_brand_and_domain(self, brand_id: int, domain: str) -> Website | None:
        target = domain.strip().lower()
        for row in self._items.values():
            if row.brand_id == brand_id and row.domain == target:
                return row
        return None

    def count_by_brand(self, brand_id: int) -> int:
        return sum(1 for r in self._items.values() if r.brand_id == brand_id)

    def count_all(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
        status: str | None = None,
    ) -> int:
        rows = list(self._items.values())
        if brand_id is not None:
            rows = [r for r in rows if r.brand_id == brand_id]
        if website_id is not None:
            rows = [r for r in rows if r.id == website_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return len(rows)

    def count_due(
        self,
        *,
        now: datetime,
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> int:
        rows = self.list_due_for_scan(now=now)
        if brand_id is not None:
            rows = [r for r in rows if r.brand_id == brand_id]
        if website_id is not None:
            rows = [r for r in rows if r.id == website_id]
        return len(rows)

    def create(self, data: dict[str, Any]) -> Website:
        self._seq += 1
        now = utc_now_naive()
        defaults = {
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


class InMemoryArticleRepository:
    def __init__(self, website_repo: InMemoryWebsiteRepository) -> None:
        self.website_repo = website_repo
        self._items: dict[int, SourceArticle] = {}
        self._revisions: list[SourceArticleRevision] = []
        self._seq = 0
        self._rev_seq = 0

    def _matches_brand(self, article: SourceArticle, brand_id: int) -> bool:
        site = self.website_repo.get_by_id(article.website_id)
        return site is not None and site.brand_id == brand_id

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
        website_id: int | None = None,
        language: str | None = None,
        category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        change_filter: str | None = None,
    ) -> tuple[list[SourceArticle], int]:
        rows = sorted(self._items.values(), key=lambda r: r.id, reverse=True)
        if brand_id is not None:
            rows = [r for r in rows if self._matches_brand(r, brand_id)]
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if language:
            rows = [r for r in rows if (r.language or "") == language.strip()]
        if category:
            cat_l = category.strip().lower()
            rows = [r for r in rows if any(str(c).lower() == cat_l for c in (r.categories or []))]
        if status:
            rows = [r for r in rows if r.status == status.strip()]
        if change_filter == "updated":
            rows = [r for r in rows if r.status == "updated"]
        elif change_filter == "new":
            rows = [r for r in rows if r.status in {"discovered", "extracted", "optimized"}]
        if date_from is not None:
            cutoff = date_from.replace(tzinfo=None)
            rows = [r for r in rows if r.discovered_at >= cutoff]
        if date_to is not None:
            cutoff = date_to.replace(tzinfo=None)
            rows = [r for r in rows if r.discovered_at <= cutoff]
        if search:
            term = search.strip().lower()
            rows = [
                r
                for r in rows
                if term in r.title.lower()
                or term in (r.meta_description or "").lower()
                or term in r.canonical_url.lower()
            ]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def get_by_id(self, article_id: int) -> SourceArticle | None:
        return self._items.get(article_id)

    def get_by_website_and_url_hash(
        self,
        website_id: int,
        url_hash: str,
    ) -> SourceArticle | None:
        for row in self._items.values():
            if row.website_id == website_id and row.url_hash == url_hash:
                return row
        return None

    def list_recent_for_website(self, website_id: int, *, limit: int = 50) -> list[SourceArticle]:
        rows = [r for r in self._items.values() if r.website_id == website_id]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows[:limit]

    def count_by_website(self, website_id: int) -> int:
        return sum(1 for r in self._items.values() if r.website_id == website_id)

    def count_all(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
        status: str | None = None,
        discovered_since: datetime | None = None,
    ) -> int:
        rows = list(self._items.values())
        if brand_id is not None:
            rows = [r for r in rows if self._matches_brand(r, brand_id)]
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if discovered_since is not None:
            cutoff = discovered_since.replace(tzinfo=None)
            rows = [r for r in rows if r.discovered_at >= cutoff]
        return len(rows)

    def create(self, data: dict[str, Any]) -> SourceArticle:
        self._seq += 1
        now = utc_now_naive()
        defaults = {
            "word_count": 0,
            "status": "extracted",
            "is_historical_baseline": False,
            "discovered_at": now,
            "last_checked_at": now,
            "created_at": now,
            "updated_at": now,
        }
        merged = {**defaults, **data}
        article = SourceArticle(id=self._seq, **merged)
        self._items[article.id] = article
        return article

    def update(self, article_id: int, data: dict[str, Any]) -> SourceArticle | None:
        article = self._items.get(article_id)
        if article is None:
            return None
        for key, value in data.items():
            setattr(article, key, value)
        article.updated_at = utc_now_naive()
        return article

    def list_revisions(self, article_id: int) -> list[SourceArticleRevision]:
        rows = [r for r in self._revisions if r.article_id == article_id]
        rows.sort(key=lambda r: r.revision_number, reverse=True)
        return rows

    def get_next_revision_number(self, article_id: int) -> int:
        revs = self.list_revisions(article_id)
        return (revs[0].revision_number if revs else 0) + 1

    def create_revision(
        self,
        *,
        article_id: int,
        revision_number: int,
        title: str,
        meta_description: str | None,
        markdown_content: str | None,
        content_hash: str,
    ) -> SourceArticleRevision:
        self._rev_seq += 1
        rev = SourceArticleRevision(
            id=self._rev_seq,
            article_id=article_id,
            revision_number=revision_number,
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
        self._seq = 0

    def _matches_brand(self, scan: WebsiteScanLog, brand_id: int) -> bool:
        site = self.website_repo.get_by_id(scan.website_id)
        return site is not None and site.brand_id == brand_id

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
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> list[WebsiteScanLog]:
        rows = sorted(self._items.values(), key=lambda s: s.id, reverse=True)
        if brand_id is not None:
            rows = [s for s in rows if self._matches_brand(s, brand_id)]
        if website_id is not None:
            rows = [s for s in rows if s.website_id == website_id]
        return rows[:limit]

    def count_by_status(
        self,
        status: str,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> int:
        rows = [s for s in self._items.values() if s.status == status]
        if brand_id is not None:
            rows = [s for s in rows if self._matches_brand(s, brand_id)]
        if website_id is not None:
            rows = [s for s in rows if s.website_id == website_id]
        return len(rows)

    def create(
        self,
        *,
        website_id: int,
        scan_method: str,
        trigger_type: str,
        status: str = "pending",
    ) -> WebsiteScanLog:
        self._seq += 1
        now = utc_now_naive()
        scan = WebsiteScanLog(
            id=self._seq,
            website_id=website_id,
            scan_method=scan_method,
            trigger_type=trigger_type,
            urls_found=0,
            articles_processed=0,
            new_articles=0,
            updated_articles=0,
            unchanged_articles=0,
            skipped_articles=0,
            failed_articles=0,
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
                scan.status = "failed"
                scan.completed_at = now
                scan.error_message = (
                    f"Recovered stale scan after exceeding {stale_minutes} "
                    "minute heartbeat timeout."
                )
                recovered.append(scan)
        return recovered


class InMemoryMediaRepository:
    def __init__(self) -> None:
        self._items: dict[int, MediaAsset] = {}
        self._seq = 0

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
    ) -> tuple[list[MediaAsset], int]:
        rows = sorted(self._items.values(), key=lambda r: r.id, reverse=True)
        if brand_id is not None:
            rows = [r for r in rows if r.brand_id == brand_id]
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
        self, source_url: str, *, brand_id: int | None = None
    ) -> MediaAsset | None:
        for row in self._items.values():
            if row.source_url == source_url and (brand_id is None or row.brand_id == brand_id):
                return row
        return None

    def create(
        self,
        *,
        brand_id: int | None,
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
            brand_id=brand_id,
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
    )


@pytest.fixture()
def memory_repos() -> dict[str, Any]:
    website_repo = InMemoryWebsiteRepository()
    return {
        "users": InMemoryUserRepository(),
        "sessions": InMemorySessionRepository(),
        "settings": InMemorySettingsRepository(),
        "activities": InMemoryActivityLogRepository(),
        "brands": InMemoryBrandRepository(),
        "websites": website_repo,
        "articles": InMemoryArticleRepository(website_repo),
        "scans": InMemoryScanLogRepository(website_repo),
        "media": InMemoryMediaRepository(),
        "rate_limiter": SlidingWindowRateLimiter(max_attempts=3, window_seconds=300),
        "dispatched_scans": [],
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
    application.dependency_overrides[get_brand_repo] = lambda: memory_repos["brands"]
    application.dependency_overrides[get_website_repo] = lambda: memory_repos["websites"]
    application.dependency_overrides[get_article_repo] = lambda: memory_repos["articles"]
    application.dependency_overrides[get_scan_log_repo] = lambda: memory_repos["scans"]
    application.dependency_overrides[get_media_repo] = lambda: memory_repos["media"]
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
