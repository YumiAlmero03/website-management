from __future__ import annotations

from datetime import datetime
from typing import Any

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


class AiGenerationJob(TimestampMixin, Base):
    __tablename__ = "ai_generation_jobs"
    __table_args__ = (
        UniqueConstraint("job_uuid", name="uq_ai_generation_jobs_uuid"),
        UniqueConstraint("idempotency_key", name="uq_ai_generation_jobs_idempotency"),
        Index("ix_ai_generation_jobs_claim", "status", "next_retry_at", "id"),
        Index("ix_ai_generation_jobs_stale", "status", "heartbeat_at"),
        Index("ix_ai_generation_jobs_website_content", "website_id", "website_content_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    job_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="social_generation", server_default="social_generation"
    )
    trigger_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_ai_jobs_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    website_content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("website_contents.id", name="fk_ai_jobs_content_id", ondelete="SET NULL"),
        nullable=True,
    )
    target_profile_ids_json: Mapped[list[int]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ai_provider_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ai_providers.id", name="fk_ai_jobs_provider_id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("prompt_templates.id", name="fk_ai_jobs_prompt_id", ondelete="SET NULL"),
        nullable=True,
    )
    context_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="optimized", server_default="optimized"
    )
    force_regenerate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    regenerate_social_post_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    defer_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_ai_jobs_created_by", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
