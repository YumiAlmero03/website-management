from __future__ import annotations

from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.media_asset import MediaAsset


class MediaRepositoryProtocol(Protocol):
    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
    ) -> tuple[list[MediaAsset], int]: ...

    def get_by_id(self, media_id: int) -> MediaAsset | None: ...

    def get_by_checksum(self, checksum: str) -> MediaAsset | None: ...

    def get_by_source_url(
        self, source_url: str, *, website_id: int | None = None
    ) -> MediaAsset | None: ...

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
    ) -> MediaAsset: ...


class SQLAlchemyMediaRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
    ) -> tuple[list[MediaAsset], int]:
        count_stmt = select(func.count()).select_from(MediaAsset)
        data_stmt = select(MediaAsset).order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        if website_id is not None:
            count_stmt = count_stmt.where(MediaAsset.website_id == website_id)
            data_stmt = data_stmt.where(MediaAsset.website_id == website_id)
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(data_stmt.offset((page - 1) * page_size).limit(page_size))
            .scalars()
            .all()
        )
        return rows, total

    def get_by_id(self, media_id: int) -> MediaAsset | None:
        return self.db.get(MediaAsset, media_id)

    def get_by_checksum(self, checksum: str) -> MediaAsset | None:
        stmt = select(MediaAsset).where(MediaAsset.checksum == checksum).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_source_url(
        self, source_url: str, *, website_id: int | None = None
    ) -> MediaAsset | None:
        stmt = select(MediaAsset).where(MediaAsset.source_url == source_url)
        if website_id is not None:
            stmt = stmt.where(MediaAsset.website_id == website_id)
        return self.db.execute(stmt.limit(1)).scalar_one_or_none()

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
        asset = MediaAsset(
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
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset
