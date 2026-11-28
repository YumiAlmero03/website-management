from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, utc_now_naive


class AiGenerationLog(Base):
    __tablename__ = "ai_generation_logs"
    __table_args__ = (
        Index("ix_ai_generation_logs_created", "created_at"),
        Index("ix_ai_generation_logs_provider_created", "ai_provider_id", "created_at"),
        Index("ix_ai_generation_logs_website_created", "website_id", "created_at"),
        Index("ix_ai_generation_logs_status", "status", "created_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ai_generation_jobs.id", name="fk_ai_logs_job_id", ondelete="SET NULL"),
        nullable=True,
    )
    ai_provider_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ai_providers.id", name="fk_ai_logs_provider_id", ondelete="RESTRICT"),
        nullable=False,
    )
    prompt_template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("prompt_templates.id", name="fk_ai_logs_prompt_id", ondelete="SET NULL"),
        nullable=True,
    )
    website_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_ai_logs_website_id", ondelete="SET NULL"),
        nullable=True,
    )
    website_content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("website_contents.id", name="fk_ai_logs_content_id", ondelete="SET NULL"),
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    context_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="optimized", server_default="optimized"
    )
    cache_hit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    cache_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measured_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measured_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_measured_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unknown", server_default="unknown"
    )
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truncated_input: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    truncation_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    encrypted_prompt_exchange: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True, deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
