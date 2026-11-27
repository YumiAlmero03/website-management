from __future__ import annotations

import re

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now
from app.models.website_category import WebsiteCategory
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.category import (
    WebsiteCategoryCreateRequest,
    WebsiteCategoryListResponse,
    WebsiteCategoryResponse,
    WebsiteCategoryUpdateRequest,
)


def slugify_label(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return cleaned[:110]


class WebsiteCategoryService:
    """Service layer for administrator-defined website categories under Settings."""

    def __init__(
        self,
        *,
        category_repo: WebsiteCategoryRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
    ) -> None:
        self.category_repo = category_repo
        self.website_repo = website_repo
        self.activity_repo = activity_repo

    def _to_response(self, cat: WebsiteCategory) -> WebsiteCategoryResponse:
        now = utc_now()
        return WebsiteCategoryResponse(
            id=cat.id,
            name=cat.name,
            slug=cat.slug,
            description=cat.description,
            is_archived=cat.is_archived,
            sort_order=cat.sort_order,
            website_count=self.website_repo.count_by_category(cat.id),
            created_at=ensure_utc(cat.created_at) or now,
            updated_at=ensure_utc(cat.updated_at) or now,
        )

    def list_categories(self, *, include_archived: bool = False) -> WebsiteCategoryListResponse:
        rows = self.category_repo.list_all(include_archived=include_archived)
        return WebsiteCategoryListResponse(items=[self._to_response(row) for row in rows])

    def get_category(self, category_id: int) -> WebsiteCategoryResponse:
        cat = self.category_repo.get_by_id(category_id)
        if cat is None:
            raise NotFoundError(f"Website category #{category_id} not found.")
        return self._to_response(cat)

    def create_category(
        self,
        payload: WebsiteCategoryCreateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteCategoryResponse:
        name = payload.name.strip()
        if len(name) < 2:
            raise ValidationAppError("Category name must be at least 2 characters.")
        slug = slugify_label(payload.slug or name)
        if not slug:
            raise ValidationAppError("Category slug could not be derived cleanly.")

        if self.category_repo.get_by_name(name) is not None:
            raise ConflictError(f"Website category '{name}' already exists.")
        if self.category_repo.get_by_slug(slug) is not None:
            raise ConflictError(f"Website category slug '{slug}' already exists.")

        created = self.category_repo.create(
            {
                "name": name,
                "slug": slug,
                "description": payload.description.strip() if payload.description else None,
                "is_archived": False,
                "sort_order": payload.sort_order,
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="settings",
            action="website_category.created",
            level="info",
            message=f"Created website category '{created.name}'.",
            metadata={"category_id": created.id, "slug": created.slug},
            ip_address=ip_address,
        )
        return self._to_response(created)

    def update_category(
        self,
        category_id: int,
        payload: WebsiteCategoryUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteCategoryResponse:
        existing = self.category_repo.get_by_id(category_id)
        if existing is None:
            raise NotFoundError(f"Website category #{category_id} not found.")

        raw = payload.model_dump(exclude_unset=True)
        updates: dict[str, object] = {}

        if "name" in raw and raw["name"] is not None:
            name = str(raw["name"]).strip()
            if len(name) < 2:
                raise ValidationAppError("Category name must be at least 2 characters.")
            conflict_name = self.category_repo.get_by_name(name)
            if conflict_name is not None and conflict_name.id != category_id:
                raise ConflictError(f"Website category '{name}' already exists.")
            updates["name"] = name

        if "slug" in raw and raw["slug"] is not None:
            slug = slugify_label(str(raw["slug"]))
            if not slug:
                raise ValidationAppError("Category slug cannot be empty.")
            conflict_slug = self.category_repo.get_by_slug(slug)
            if conflict_slug is not None and conflict_slug.id != category_id:
                raise ConflictError(f"Website category slug '{slug}' already exists.")
            updates["slug"] = slug

        if "description" in raw:
            desc = raw["description"]
            updates["description"] = (
                desc.strip() if isinstance(desc, str) and desc.strip() else None
            )

        if "is_archived" in raw and raw["is_archived"] is not None:
            updates["is_archived"] = bool(raw["is_archived"])

        if "sort_order" in raw and raw["sort_order"] is not None:
            updates["sort_order"] = int(raw["sort_order"])

        updated = self.category_repo.update(category_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="settings",
            action="website_category.updated",
            level="info",
            message=f"Updated website category '{updated.name}'.",
            metadata={"category_id": updated.id, "updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def delete_category(
        self,
        category_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> None:
        existing = self.category_repo.get_by_id(category_id)
        if existing is None:
            raise NotFoundError(f"Website category #{category_id} not found.")

        usage_count = self.website_repo.count_by_category(category_id)
        if usage_count > 0:
            raise ConflictError(
                f"Cannot delete category '{existing.name}' because {usage_count} "
                "website(s) are assigned to it. Reassign websites or archive the category instead."
            )

        self.category_repo.delete(category_id)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="settings",
            action="website_category.deleted",
            level="warning",
            message=f"Deleted website category '{existing.name}'.",
            metadata={"category_id": category_id, "slug": existing.slug},
            ip_address=ip_address,
        )
