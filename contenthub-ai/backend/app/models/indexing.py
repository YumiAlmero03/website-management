from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class IndexingJob(TimestampMixin, Base):
    __tablename__ = "indexing_jobs"
    __table_args__ = (
        Index("ix_indexing_jobs_claim", "website_id", "status", "available_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_index_job_website", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ready_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=lambda: datetime.utcnow()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    deferred_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)


class IndexingHistory(TimestampMixin, Base):
    __tablename__ = "indexing_history"
    __table_args__ = (
        Index("ix_indexing_history_site_content", "website_id", "website_content_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("indexing_jobs.id", name="fk_index_history_job", ondelete="SET NULL"),
        nullable=True,
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_index_history_website", ondelete="CASCADE"),
        nullable=False,
    )
    website_content_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("website_contents.id", name="fk_index_history_content", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    inspection_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    technical_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
