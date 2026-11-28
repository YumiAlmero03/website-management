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

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin, utc_now_naive


class ContentKeyword(TimestampMixin, Base):
    __tablename__ = "content_keywords"
    __table_args__ = (
        UniqueConstraint("website_content_id", name="uq_content_keywords_content_id"),
        Index("ix_content_keywords_website_status", "website_id", "approval_status"),
        Index("ix_content_keywords_website_norm", "website_id", "focus_keyphrase_norm"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_content_keywords_website_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    website_content_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_contents.id",
            name="fk_content_keywords_content_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    focus_keyphrase: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    focus_keyphrase_norm: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    secondary_keywords_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    anchor_text_variations_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    keyword_generation_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="python", server_default="python"
    )
    keyword_generation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    keyword_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    keyword_scores_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    keyword_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    keyword_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    keyword_generated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    game_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_alt_suggestions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    approval_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_review",
        server_default="pending_review",
    )
    suggestion_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="python_auto",
        server_default="python_auto",
    )
    is_admin_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_content_keywords_approved_by", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_content_keywords_created_by", ondelete="SET NULL"),
        nullable=True,
    )


class ContentKeywordRevision(Base):
    __tablename__ = "content_keyword_revisions"
    __table_args__ = (
        UniqueConstraint(
            "content_keyword_id",
            "revision_number",
            name="uq_content_keyword_revisions_num",
        ),
        Index("ix_content_keyword_revisions_kw", "content_keyword_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    content_keyword_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "content_keywords.id",
            name="fk_content_keyword_revisions_kw_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    focus_keyphrase: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    secondary_keywords_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    anchor_text_variations_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    image_alt_suggestions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    suggestion_source: Mapped[str] = mapped_column(String(32), nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_content_keyword_revisions_user", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
