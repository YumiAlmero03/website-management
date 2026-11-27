from __future__ import annotations

import math
import re
from urllib.parse import urlparse

from app.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now
from app.models.brand import Brand
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.brand_repo import BrandRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.brand import (
    BrandCreateRequest,
    BrandDetailResponse,
    BrandListResponse,
    BrandResponse,
    BrandUpdateRequest,
    BrandWebsiteSummary,
)
from app.schemas.common import PaginationMeta
from app.services.content.media import (
    ALLOWED_IMAGE_MIMES,
    MediaValidationError,
    validate_image_bytes,
)

_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _SLUG_CLEAN_RE.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ValidationAppError("Brand slug must contain at least one alphanumeric character.")
    return slug[:150]


def _clean_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        lowered = item.lower()
        if item and lowered not in seen:
            seen.add(lowered)
            result.append(item)
    return result


def _validate_logo_url(url: str | None) -> str | None:
    if url is None:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    if cleaned.startswith("/api/v1/media/"):
        return cleaned
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValidationAppError("Logo URL must be a valid http(s) URL or uploaded media path.")
    if parsed.username or parsed.password:
        raise ValidationAppError("Logo URL must not contain embedded credentials.")
    return cleaned


class BrandService:
    def __init__(
        self,
        *,
        settings: Settings,
        brand_repo: BrandRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.brand_repo = brand_repo
        self.website_repo = website_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo

    def _to_response(self, brand: Brand) -> BrandResponse:
        now = utc_now()
        return BrandResponse(
            id=brand.id,
            name=brand.name,
            slug=brand.slug,
            logo_url=brand.logo_url,
            description=brand.description,
            target_audience=brand.target_audience,
            target_country=brand.target_country,
            primary_language=brand.primary_language,
            secondary_languages=list(brand.secondary_languages or []),
            tone=brand.tone,
            target_keywords=list(brand.target_keywords or []),
            restricted_keywords=list(brand.restricted_keywords or []),
            default_hashtags=list(brand.default_hashtags or []),
            default_cta=brand.default_cta,
            writing_guidelines=brand.writing_guidelines,
            ai_instructions=brand.ai_instructions,
            is_active=brand.is_active,
            website_count=self.website_repo.count_by_brand(brand.id),
            created_at=ensure_utc(brand.created_at) or now,
            updated_at=ensure_utc(brand.updated_at) or now,
        )

    def list_brands(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
        language: str | None = None,
    ) -> BrandListResponse:
        rows, total = self.brand_repo.list_paginated(
            page=page,
            page_size=page_size,
            search=search,
            is_active=is_active,
            language=language,
        )
        items = [self._to_response(row) for row in rows]
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return BrandListResponse(
            items=items,
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
        )

    def get_brand_detail(self, brand_id: int) -> BrandDetailResponse:
        brand = self.brand_repo.get_by_id(brand_id)
        if brand is None:
            raise NotFoundError(f"Brand #{brand_id} not found.")
        base = self._to_response(brand)
        websites = self.website_repo.list_by_brand(brand_id)
        summaries = [
            BrandWebsiteSummary(
                id=site.id,
                name=site.name,
                domain=site.domain,
                website_type=site.website_type,
                status=site.status,
                last_successful_scan_at=ensure_utc(site.last_successful_scan_at),
            )
            for site in websites
        ]
        return BrandDetailResponse(**base.model_dump(), websites=summaries)

    def create_brand(
        self,
        payload: BrandCreateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> BrandResponse:
        resolved_slug = slugify(payload.slug or payload.name)
        if self.brand_repo.get_by_slug(resolved_slug) is not None:
            raise ConflictError(f"A brand with slug '{resolved_slug}' already exists.")

        logo_url = _validate_logo_url(payload.logo_url)
        data = {
            "name": payload.name.strip(),
            "slug": resolved_slug,
            "logo_url": logo_url,
            "description": payload.description.strip() if payload.description else None,
            "target_audience": payload.target_audience.strip() if payload.target_audience else None,
            "target_country": payload.target_country.strip() if payload.target_country else None,
            "primary_language": payload.primary_language.strip(),
            "secondary_languages": _clean_string_list(payload.secondary_languages),
            "tone": payload.tone.strip() if payload.tone else None,
            "target_keywords": _clean_string_list(payload.target_keywords),
            "restricted_keywords": _clean_string_list(payload.restricted_keywords),
            "default_hashtags": _clean_string_list(payload.default_hashtags),
            "default_cta": payload.default_cta.strip() if payload.default_cta else None,
            "writing_guidelines": payload.writing_guidelines.strip()
            if payload.writing_guidelines
            else None,
            "ai_instructions": payload.ai_instructions.strip() if payload.ai_instructions else None,
            "is_active": payload.is_active,
        }
        brand = self.brand_repo.create(data)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="brands",
            action="brand.created",
            level="info",
            message=f"Created brand '{brand.name}' ({brand.slug}).",
            metadata={"brand_id": brand.id, "slug": brand.slug},
            ip_address=ip_address,
        )
        return self._to_response(brand)

    def update_brand(
        self,
        brand_id: int,
        payload: BrandUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> BrandResponse:
        existing = self.brand_repo.get_by_id(brand_id)
        if existing is None:
            raise NotFoundError(f"Brand #{brand_id} not found.")

        raw_updates = payload.model_dump(exclude_unset=True)
        updates: dict[str, object] = {}

        if "slug" in raw_updates and raw_updates["slug"] is not None:
            next_slug = slugify(raw_updates["slug"])
            conflict = self.brand_repo.get_by_slug(next_slug)
            if conflict is not None and conflict.id != brand_id:
                raise ConflictError(f"A brand with slug '{next_slug}' already exists.")
            updates["slug"] = next_slug

        if "logo_url" in raw_updates:
            updates["logo_url"] = _validate_logo_url(raw_updates["logo_url"])

        for text_field in (
            "name",
            "description",
            "target_audience",
            "target_country",
            "primary_language",
            "tone",
            "default_cta",
            "writing_guidelines",
            "ai_instructions",
        ):
            if text_field in raw_updates:
                val = raw_updates[text_field]
                updates[text_field] = val.strip() if isinstance(val, str) and val.strip() else None

        for list_field in (
            "secondary_languages",
            "target_keywords",
            "restricted_keywords",
            "default_hashtags",
        ):
            if list_field in raw_updates:
                updates[list_field] = _clean_string_list(raw_updates[list_field])

        if "is_active" in raw_updates and raw_updates["is_active"] is not None:
            updates["is_active"] = bool(raw_updates["is_active"])

        updated = self.brand_repo.update(brand_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="brands",
            action="brand.updated",
            level="info",
            message=f"Updated brand '{updated.name}'.",
            metadata={"brand_id": updated.id, "updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def delete_brand(
        self,
        brand_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> None:
        brand = self.brand_repo.get_by_id(brand_id)
        if brand is None:
            raise NotFoundError(f"Brand #{brand_id} not found.")

        website_count = self.website_repo.count_by_brand(brand_id)
        if website_count > 0:
            raise ConflictError(
                f"Cannot permanently delete brand '{brand.name}' because {website_count} "
                "associated website(s) still reference it. Archive/deactivate the brand instead, "
                "or reassign/remove associated websites first."
            )

        self.brand_repo.delete(brand_id)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="brands",
            action="brand.deleted",
            level="warning",
            message=f"Deleted brand '{brand.name}' ({brand.slug}).",
            metadata={"brand_id": brand_id, "slug": brand.slug},
            ip_address=ip_address,
        )

    def upload_logo(
        self,
        brand_id: int,
        *,
        file_bytes: bytes,
        declared_mime: str | None,
        user_id: int,
        ip_address: str | None,
    ) -> BrandResponse:
        brand = self.brand_repo.get_by_id(brand_id)
        if brand is None:
            raise NotFoundError(f"Brand #{brand_id} not found.")

        try:
            mime_type, width, height, checksum = validate_image_bytes(
                file_bytes,
                max_file_bytes=self.settings.media_max_file_bytes,
                max_dimension_px=self.settings.media_max_dimension_px,
                declared_mime=declared_mime,
            )
        except MediaValidationError as exc:
            raise ValidationAppError(str(exc)) from exc

        existing = self.media_repo.get_by_checksum(checksum)
        if existing is not None:
            asset = existing
        else:
            ext = ALLOWED_IMAGE_MIMES[mime_type]
            safe_name = f"brand-{brand.id}-{checksum[:16]}.{ext}"
            images_dir = self.settings.resolved_storage_root / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            dest = (images_dir / safe_name).resolve()
            dest.write_bytes(file_bytes)
            asset = self.media_repo.create(
                brand_id=brand.id,
                file_name=safe_name,
                file_path=f"images/{safe_name}",
                source_url=None,
                mime_type=mime_type,
                file_size=len(file_bytes),
                width=width,
                height=height,
                alt_text=f"{brand.name} logo",
                checksum=checksum,
            )

        updated = self.brand_repo.update(brand.id, {"logo_url": f"/api/v1/media/{asset.id}/file"})
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="brands",
            action="brand.logo_uploaded",
            level="info",
            message=f"Uploaded validated logo for brand '{brand.name}'.",
            metadata={"brand_id": brand.id, "media_asset_id": asset.id},
            ip_address=ip_address,
        )
        return self._to_response(updated)
