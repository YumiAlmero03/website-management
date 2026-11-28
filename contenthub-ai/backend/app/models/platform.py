from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class Platform(TimestampMixin, Base):
    __tablename__ = "platforms"
    __table_args__ = (
        UniqueConstraint("platform_key", name="uq_platforms_platform_key"),
        Index("ix_platforms_sort_enabled", "is_enabled", "sort_order"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="social",
        server_default="social",
    )
    default_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url_counts_as_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_hashtags: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    supports_cta: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    supports_source_url: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    supports_title: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    supports_media: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    supports_free_auto_publish: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    credential_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default=text("100")
    )
