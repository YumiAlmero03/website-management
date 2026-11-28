from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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


class SocialPost(TimestampMixin, Base):
    __tablename__ = "social_posts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_social_posts_dedupe_key"),
        Index("ix_social_posts_status", "status", "created_at"),
        Index("ix_social_posts_publishing_status", "publishing_status", "scheduled_for"),
        Index("ix_social_posts_published_at", "published_at"),
        Index("ix_social_posts_website_profile", "website_id", "social_profile_id"),
        Index("ix_social_posts_content", "website_content_id"),
        Index("ix_social_posts_platform", "platform_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_social_posts_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    website_content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("website_contents.id", name="fk_social_posts_content_id", ondelete="SET NULL"),
        nullable=True,
    )
    social_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "social_profiles.id",
            name="fk_social_posts_social_profile_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    platform_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platforms.id", name="fk_social_posts_platform_id", ondelete="RESTRICT"),
        nullable=False,
    )
    featured_media_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("media_assets.id", name="fk_social_posts_media_id", ondelete="SET NULL"),
        nullable=True,
    )
    ai_generation_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ai_generation_jobs.id", name="fk_social_posts_job_id", ondelete="SET NULL"),
        nullable=True,
    )
    ai_provider_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ai_providers.id", name="fk_social_posts_provider_id", ondelete="SET NULL"),
        nullable=True,
    )
    generation_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("prompt_templates.id", name="fk_social_posts_prompt_id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    assembled_content: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cta_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    language: Mapped[str] = mapped_column(
        String(32), nullable=False, default="en", server_default="en"
    )
    character_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    character_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_review", server_default="pending_review"
    )
    is_manually_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_social_posts_approved_by", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_social_posts_rejected_by", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    publishing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unscheduled", server_default="unscheduled"
    )
    approved_revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    alternative_captions_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    utm_params_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    target_url_with_utm: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    display_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified", server_default="unverified"
    )
    last_publish_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_publish_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class SocialPostRevision(Base):
    __tablename__ = "social_post_revisions"
    __table_args__ = (
        UniqueConstraint("social_post_id", "version_number", name="uq_social_post_revs_ver"),
        Index("ix_social_post_revs_post", "social_post_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    social_post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("social_posts.id", name="fk_social_post_revs_post_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    assembled_content: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cta_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generation_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    change_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="initial_generated", server_default="initial_generated"
    )
    edited_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_social_post_revs_edited_by", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
