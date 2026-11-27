from __future__ import annotations

from app.models.content_revision import ContentRevision
from app.models.website_content import WebsiteContent
from app.repositories.content_repo import ContentRepositoryProtocol


def has_content_changed(existing: WebsiteContent, new_content_hash: str) -> bool:
    """Return True when the newly extracted content hash differs from the stored hash."""
    return existing.content_hash != new_content_hash


def create_revision_snapshot(
    content_repo: ContentRepositoryProtocol,
    existing: WebsiteContent,
) -> ContentRevision:
    """Snapshot the previous version of a website_content record before overwriting changes."""
    next_rev = content_repo.get_next_revision_number(existing.id)
    return content_repo.create_revision(
        content_id=existing.id,
        revision_number=next_rev,
        title=existing.title,
        meta_description=existing.meta_description,
        markdown_content=existing.markdown_content,
        content_hash=existing.content_hash,
        content_type=existing.content_type,
    )
