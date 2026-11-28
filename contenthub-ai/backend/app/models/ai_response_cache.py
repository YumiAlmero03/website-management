from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, utc_now_naive


class AiResponseCache(Base):
    __tablename__ = "ai_response_cache"
    __table_args__ = (
        UniqueConstraint("cache_key_hash", name="uq_ai_response_cache_key_hash"),
        Index("ix_ai_response_cache_website", "website_id", "task_type"),
        Index("ix_ai_response_cache_expires_at", "expires_at"),
        Index("ix_ai_response_cache_source_hash", "source_content_hash"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cache_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_provider_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ai_providers.id", name="fk_ai_cache_provider_id", ondelete="CASCADE"),
        nullable=False,
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_ai_cache_website_id", ondelete="CASCADE"),
        nullable=False,
    )
    website_content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("website_contents.id", name="fk_ai_cache_content_id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("prompt_templates.id", name="fk_ai_cache_prompt_id", ondelete="SET NULL"),
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="optimized", server_default="optimized"
    )
    language: Mapped[str] = mapped_column(
        String(32), nullable=False, default="en", server_default="en"
    )
    schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="v1", server_default="v1"
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
