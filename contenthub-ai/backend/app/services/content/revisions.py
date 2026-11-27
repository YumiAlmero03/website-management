from __future__ import annotations

from app.models.source_article import SourceArticle
from app.models.source_article_revision import SourceArticleRevision
from app.repositories.article_repo import ArticleRepositoryProtocol


def has_content_changed(existing: SourceArticle, new_content_hash: str) -> bool:
    return existing.content_hash != new_content_hash


def create_revision_snapshot(
    article_repo: ArticleRepositoryProtocol,
    existing: SourceArticle,
) -> SourceArticleRevision:
    """Snapshot the previous version of a source_article before overwriting changed content."""
    next_rev = article_repo.get_next_revision_number(existing.id)
    return article_repo.create_revision(
        article_id=existing.id,
        revision_number=next_rev,
        title=existing.title,
        meta_description=existing.meta_description,
        markdown_content=existing.markdown_content,
        content_hash=existing.content_hash,
    )
