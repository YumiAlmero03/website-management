from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin, utc_now_naive

LONG_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")
MEDIUM_TEXT = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class WebsiteContent(TimestampMixin, Base):
    __tablename__ = "website_contents"
    __table_args__ = (
        UniqueConstraint("website_id", "url_hash", name="uq_website_contents_website_url_hash"),
        Index("ix_website_contents_website_type", "website_id", "content_type"),
        Index("ix_website_contents_extraction_status", "website_id", "extraction_status"),
        Index("ix_website_contents_content_hash", "content_hash"),
        Index("ix_website_contents_published_at", "published_at"),
        Index("ix_website_contents_status", "status"),
        Index(
            "ft_website_contents_search",
            "title",
            "meta_description",
            "markdown_content",
            mysql_prefix="FULLTEXT",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_website_contents_website_id_websites",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    featured_media_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "media_assets.id",
            name="fk_website_contents_featured_media_id_media_assets",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    content_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="page",
        server_default="page",
    )
    classification_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="default_rule",
        server_default="default_rule",
    )
    manual_classification_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    is_excluded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(150), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_content: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    extracted_content: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    markdown_content: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    optimized_context: Mapped[str | None] = mapped_column(MEDIUM_TEXT, nullable=True)
    structured_data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    categories: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    word_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="extracted",
        server_default="extracted",
    )
    extraction_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="extracted",
        server_default="extracted",
    )
    discovery_sources: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_historical_baseline: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    near_duplicate_of_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_contents.id",
            name="fk_website_contents_near_duplicate_of_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    near_duplicate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    first_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
