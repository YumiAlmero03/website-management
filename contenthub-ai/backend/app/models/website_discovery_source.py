from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class WebsiteDiscoverySource(TimestampMixin, Base):
    __tablename__ = "website_discovery_sources"
    __table_args__ = (
        UniqueConstraint(
            "website_id",
            "endpoint_hash",
            name="uq_website_discovery_sources_site_ep",
        ),
        Index(
            "ix_website_discovery_sources_website_type",
            "website_id",
            "source_type",
            "is_enabled",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_wds_website_id_websites",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    parent_source_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_discovery_sources.id",
            name="fk_wds_parent_source_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    endpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified_header: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_urls_found: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
