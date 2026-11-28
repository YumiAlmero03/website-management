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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin, utc_now_naive


class WebsiteKnowledgeProfile(TimestampMixin, Base):
    __tablename__ = "website_knowledge_profiles"
    __table_args__ = (
        UniqueConstraint("website_id", name="uq_website_knowledge_profiles_website"),
        Index("ix_website_knowledge_profiles_status", "status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_knowledge_profiles_website_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    brand_name: Mapped[str] = mapped_column(String(150), nullable=False)
    brand_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    products_and_services: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    main_features: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    target_audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_language: Mapped[str] = mapped_column(
        String(32), nullable=False, default="en", server_default="en"
    )
    secondary_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    recommended_writing_tone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    main_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    content_pillars: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    important_internal_links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    relevant_publishing_restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_content_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    administrator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_overrides_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    field_provenance_json: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    content_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    profile_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    last_generated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_knowledge_profiles_approved_by", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )


class WebsiteKnowledgeProfileRevision(Base):
    __tablename__ = "website_knowledge_profile_revisions"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_profile_id",
            "profile_version",
            name="uq_knowledge_profile_revisions_ver",
        ),
        Index("ix_knowledge_profile_revisions_website", "website_id", "created_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_knowledge_profiles.id",
            name="fk_knowledge_rev_profile_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_knowledge_rev_website_id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    change_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="generated", server_default="generated"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_knowledge_rev_created_by", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
