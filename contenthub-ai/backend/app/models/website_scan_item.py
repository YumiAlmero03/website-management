from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class WebsiteScanItem(TimestampMixin, Base):
    __tablename__ = "website_scan_items"
    __table_args__ = (
        UniqueConstraint("scan_log_id", "url_hash", name="uq_website_scan_items_scan_url"),
        Index("ix_website_scan_items_scan_status", "scan_log_id", "status"),
        Index("ix_website_scan_items_site_status", "website_id", "status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scan_log_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_scan_logs.id",
            name="fk_wsi_scan_log_id_scan_logs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_wsi_website_id_websites",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_contents.id",
            name="fk_wsi_content_id_contents",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="page",
        server_default="page",
    )
    discovery_sources: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    discovered_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    discovered_published_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    discovered_modified_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
