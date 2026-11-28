from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin, utc_now_naive


class ContentApproval(TimestampMixin, Base):
    __tablename__ = "content_approvals"
    __table_args__ = (
        UniqueConstraint("website_content_id", name="uq_content_approvals_content_id"),
        Index("ix_content_approvals_website_status", "website_id", "status"),
        Index("ix_content_approvals_status_updated", "status", "updated_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_content_approvals_website_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    website_content_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "website_contents.id",
            name="fk_content_approvals_content_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_review",
        server_default="pending_review",
    )
    classified_content_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="page", server_default="page"
    )
    submitted_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auto_generation_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_content_approvals_reviewed_by", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class ContentApprovalHistory(Base):
    __tablename__ = "content_approval_history"
    __table_args__ = (
        Index("ix_content_approval_history_approval", "content_approval_id"),
        Index("ix_content_approval_history_created", "created_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    content_approval_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "content_approvals.id",
            name="fk_content_approval_history_approval_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    focus_keyphrase: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    acted_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_content_approval_history_user", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
