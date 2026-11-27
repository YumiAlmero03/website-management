from __future__ import annotations

import math
from pathlib import Path

from app.config import Settings
from app.core.exceptions import NotFoundError
from app.models.base import ensure_utc, utc_now
from app.models.media_asset import MediaAsset
from app.repositories.media_repo import MediaRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.media import MediaAssetListResponse, MediaAssetResponse


class MediaService:
    def __init__(
        self,
        *,
        settings: Settings,
        media_repo: MediaRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.media_repo = media_repo

    @staticmethod
    def _to_response(asset: MediaAsset) -> MediaAssetResponse:
        now = utc_now()
        return MediaAssetResponse(
            id=asset.id,
            brand_id=asset.brand_id,
            file_name=asset.file_name,
            file_path=asset.file_path,
            source_url=asset.source_url,
            mime_type=asset.mime_type,
            file_size=asset.file_size,
            width=asset.width,
            height=asset.height,
            alt_text=asset.alt_text,
            checksum=asset.checksum,
            created_at=ensure_utc(asset.created_at) or now,
        )

    def list_media(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
    ) -> MediaAssetListResponse:
        rows, total = self.media_repo.list_paginated(
            page=page,
            page_size=page_size,
            brand_id=brand_id,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return MediaAssetListResponse(
            items=[self._to_response(row) for row in rows],
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
        )

    def get_media(self, media_id: int) -> MediaAssetResponse:
        asset = self.media_repo.get_by_id(media_id)
        if asset is None:
            raise NotFoundError(f"Media asset #{media_id} not found.")
        return self._to_response(asset)

    def resolve_local_file(self, media_id: int) -> tuple[Path, str]:
        asset = self.media_repo.get_by_id(media_id)
        if asset is None or not asset.file_path:
            raise NotFoundError(f"Local media file for asset #{media_id} not found.")
        root = self.settings.resolved_storage_root.resolve()
        candidate = (root / asset.file_path).resolve()
        if not str(candidate).startswith(str(root)) or not candidate.is_file():
            raise NotFoundError(f"Local media file for asset #{media_id} not found on disk.")
        return candidate, asset.mime_type or "application/octet-stream"
