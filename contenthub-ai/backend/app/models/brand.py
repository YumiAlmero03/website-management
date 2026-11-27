from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class Brand(TimestampMixin, Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_brands_slug"),
        Index("ix_brands_is_active", "is_active"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    restricted_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    default_hashtags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    default_cta: Mapped[str | None] = mapped_column(String(255), nullable=True)
    writing_guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "slug": self.slug}
