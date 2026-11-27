from __future__ import annotations

import hashlib
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.website_discovery_source import WebsiteDiscoverySource
from app.models.website_url_rule import WebsiteUrlRule


def hash_endpoint(endpoint_url: str) -> str:
    return hashlib.sha256(endpoint_url.strip().encode("utf-8")).hexdigest()


class WebsiteSourceConfigRepositoryProtocol(Protocol):
    def list_sources(
        self, website_id: int, *, enabled_only: bool = False
    ) -> list[WebsiteDiscoverySource]: ...

    def get_source(self, source_id: int) -> WebsiteDiscoverySource | None: ...

    def get_source_by_endpoint(
        self, website_id: int, endpoint_url: str
    ) -> WebsiteDiscoverySource | None: ...

    def upsert_source(
        self,
        *,
        website_id: int,
        source_type: str,
        endpoint_url: str,
        parent_source_id: int | None = None,
        is_enabled: bool = True,
    ) -> WebsiteDiscoverySource: ...

    def update_source(
        self, source_id: int, data: dict[str, Any]
    ) -> WebsiteDiscoverySource | None: ...

    def delete_source(self, source_id: int) -> bool: ...

    def list_rules(
        self, website_id: int, *, enabled_only: bool = False
    ) -> list[WebsiteUrlRule]: ...

    def get_rule(self, rule_id: int) -> WebsiteUrlRule | None: ...

    def create_rule(self, data: dict[str, Any]) -> WebsiteUrlRule: ...

    def update_rule(self, rule_id: int, data: dict[str, Any]) -> WebsiteUrlRule | None: ...

    def delete_rule(self, rule_id: int) -> bool: ...


class SQLAlchemyWebsiteSourceConfigRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sources(
        self, website_id: int, *, enabled_only: bool = False
    ) -> list[WebsiteDiscoverySource]:
        stmt = (
            select(WebsiteDiscoverySource)
            .where(WebsiteDiscoverySource.website_id == website_id)
            .order_by(WebsiteDiscoverySource.id.asc())
        )
        if enabled_only:
            stmt = stmt.where(WebsiteDiscoverySource.is_enabled.is_(True))
        return list(self.db.execute(stmt).scalars().all())

    def get_source(self, source_id: int) -> WebsiteDiscoverySource | None:
        return self.db.get(WebsiteDiscoverySource, source_id)

    def get_source_by_endpoint(
        self, website_id: int, endpoint_url: str
    ) -> WebsiteDiscoverySource | None:
        ep_hash = hash_endpoint(endpoint_url)
        stmt = select(WebsiteDiscoverySource).where(
            WebsiteDiscoverySource.website_id == website_id,
            WebsiteDiscoverySource.endpoint_hash == ep_hash,
        )
        return self.db.execute(stmt).scalar_one_or_none()

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
        ep_hash = hash_endpoint(clean_ep)
        existing = self.get_source_by_endpoint(website_id, clean_ep)
        now = utc_now_naive()
        if existing is not None:
            existing.source_type = source_type
            if parent_source_id is not None and existing.parent_source_id is None:
                existing.parent_source_id = parent_source_id
            existing.updated_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = WebsiteDiscoverySource(
            website_id=website_id,
            parent_source_id=parent_source_id,
            source_type=source_type,
            endpoint_url=clean_ep,
            endpoint_hash=ep_hash,
            is_enabled=is_enabled,
            last_urls_found=0,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_source(self, source_id: int, data: dict[str, Any]) -> WebsiteDiscoverySource | None:
        row = self.db.get(WebsiteDiscoverySource, source_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_source(self, source_id: int) -> bool:
        row = self.db.get(WebsiteDiscoverySource, source_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def list_rules(self, website_id: int, *, enabled_only: bool = False) -> list[WebsiteUrlRule]:
        stmt = (
            select(WebsiteUrlRule)
            .where(WebsiteUrlRule.website_id == website_id)
            .order_by(WebsiteUrlRule.priority.desc(), WebsiteUrlRule.id.asc())
        )
        if enabled_only:
            stmt = stmt.where(WebsiteUrlRule.is_enabled.is_(True))
        return list(self.db.execute(stmt).scalars().all())

    def get_rule(self, rule_id: int) -> WebsiteUrlRule | None:
        return self.db.get(WebsiteUrlRule, rule_id)

    def create_rule(self, data: dict[str, Any]) -> WebsiteUrlRule:
        now = utc_now_naive()
        rule = WebsiteUrlRule(**data, created_at=now, updated_at=now)
        self.db.add(rule)
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def update_rule(self, rule_id: int, data: dict[str, Any]) -> WebsiteUrlRule | None:
        rule = self.db.get(WebsiteUrlRule, rule_id)
        if rule is None:
            return None
        for key, value in data.items():
            setattr(rule, key, value)
        rule.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def delete_rule(self, rule_id: int) -> bool:
        rule = self.db.get(WebsiteUrlRule, rule_id)
        if rule is None:
            return False
        self.db.delete(rule)
        self.db.commit()
        return True
