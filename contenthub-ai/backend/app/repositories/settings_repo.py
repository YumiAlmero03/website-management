from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.setting import ApplicationSetting


class SettingsRepositoryProtocol(Protocol):
    def list_all(self) -> list[ApplicationSetting]: ...

    def get_by_key(self, key: str) -> ApplicationSetting | None: ...

    def count_all(self) -> int: ...

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
    ) -> ApplicationSetting: ...


class SQLAlchemySettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[ApplicationSetting]:
        stmt = select(ApplicationSetting).order_by(
            ApplicationSetting.category.asc(),
            ApplicationSetting.setting_key.asc(),
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_key(self, key: str) -> ApplicationSetting | None:
        stmt = select(ApplicationSetting).where(ApplicationSetting.setting_key == key)
        return self.db.execute(stmt).scalar_one_or_none()

    def count_all(self) -> int:
        stmt = select(func.count()).select_from(ApplicationSetting)
        return int(self.db.execute(stmt).scalar_one())

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
        existing = self.get_by_key(key)
        if existing is None:
            record = ApplicationSetting(
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
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            return record

        existing.category = category
        existing.value_json = value_json
        existing.encrypted_value = encrypted_value
        existing.is_secret = is_secret
        existing.description = description
        existing.updated_by = updated_by
        existing.updated_at = now
        self.db.commit()
        self.db.refresh(existing)
        return existing
