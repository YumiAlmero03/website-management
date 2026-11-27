from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import PaginationMeta


class MediaAssetResponse(BaseModel):
    id: int
    website_id: int | None = None
    file_name: str
    file_path: str | None = None
    source_url: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    checksum: str | None = None
    created_at: datetime


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetResponse]
    meta: PaginationMeta
