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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class Website(TimestampMixin, Base):
    __tablename__ = "websites"
    __table_args__ = (
        UniqueConstraint("brand_id", "domain", name="uq_websites_brand_domain"),
        Index("ix_websites_brand_id", "brand_id"),
        Index("ix_websites_domain", "domain"),
        Index("ix_websites_status", "status"),
        Index("ix_websites_next_scan_at", "next_scan_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("brands.id", name="fk_websites_brand_id_brands", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
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
    rss_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sitemap_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llms_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    article_url_patterns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    excluded_url_patterns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    scan_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=360,
        server_default=text("360"),
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
