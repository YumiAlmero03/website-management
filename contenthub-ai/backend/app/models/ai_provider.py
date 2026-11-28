from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class AiProvider(TimestampMixin, Base):
    __tablename__ = "ai_providers"
    __table_args__ = (
        UniqueConstraint("name", name="uq_ai_providers_name"),
        Index("ix_ai_providers_default_active", "is_default", "is_active"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="gemini", server_default="gemini"
    )
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    selected_model: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="gemini-3.5-flash-lite",
        server_default="gemini-3.5-flash-lite",
    )
    available_models_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    default_temperature: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.4, server_default=text("0.4")
    )
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1500, server_default=text("1500")
    )
    request_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=45, server_default=text("45")
    )
    max_retry_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default=text("2")
    )
    daily_request_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default=text("100")
    )
    daily_token_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=250000, server_default=text("250000")
    )
    per_minute_request_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    generation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    response_caching_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    token_optimization_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    allow_paid_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    last_test_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="untested", server_default="untested"
    )
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
