from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class Website(TimestampMixin, Base):
    __tablename__ = "websites"
    __table_args__ = (
        UniqueConstraint("domain", name="uq_websites_domain"),
        Index("ix_websites_category_id", "category_id"),
        Index("ix_websites_domain", "domain"),
        Index("ix_websites_status", "status"),
        Index("ix_websites_next_scan_at", "next_scan_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_categories.id",
            name="fk_websites_category_id_categories",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)

    # Merged brand identity & localization / editorial guidance (website-centric)
    brand_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    brand_slug: Mapped[str | None] = mapped_column(String(150), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_language: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="en",
        server_default="en",
    )
    secondary_languages: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    keyword_bank: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    restricted_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    default_hashtags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    default_cta: Mapped[str | None] = mapped_column(String(255), nullable=True)
    writing_guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Technology & Discovery configuration
    website_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="wordpress",
        server_default="wordpress",
    )
    discovery_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="auto",
        server_default="auto",
    )
    single_source_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    rss_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sitemap_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llms_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gsc_property_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gsc_property_verified_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    encrypted_gsc_service_account_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_url_patterns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    excluded_url_patterns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Scheduling & Batched Crawl configuration
    scan_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1440,
        server_default=text("1440"),
    )
    crawl_batch_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default=text("100"),
    )
    crawl_max_urls_per_run: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1000,
        server_default=text("1000"),
    )
    auto_scan: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    auto_generate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    auto_generate_require_published_at: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    auto_generate_context_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="optimized",
        server_default="optimized",
    )
    initial_scan_completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    baseline_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="import_existing",
        server_default="import_existing",
    )
    baseline_after_date: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    baseline_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified_header: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_successful_scan_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
