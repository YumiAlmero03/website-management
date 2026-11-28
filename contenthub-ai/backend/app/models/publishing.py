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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin, utc_now_naive


class SocialProfileConnection(TimestampMixin, Base):
    __tablename__ = "social_profile_connections"
    __table_args__ = (
        UniqueConstraint("social_profile_id", name="uq_spc_profile_id"),
        Index("ix_spc_website_status", "website_id", "connection_status"),
        Index("ix_spc_expires", "token_expires_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    social_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("social_profiles.id", name="fk_spc_profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_spc_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platforms.id", name="fk_spc_platform_id", ondelete="RESTRICT"),
        nullable=False,
    )
    auth_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    connection_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_connected", server_default="not_connected"
    )
    account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_resource_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    available_targets_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    granted_scopes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_scopes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    missing_scopes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    eligibility_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    eligibility_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_tier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allow_paid_publishing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    api_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class OAuthStateSession(Base):
    __tablename__ = "oauth_state_sessions"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_oauth_states_hash"),
        Index("ix_oauth_states_profile_status", "social_profile_id", "status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_oauth_states_website_id", ondelete="CASCADE"),
        nullable=False,
    )
    social_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("social_profiles.id", name="fk_oauth_states_profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_code_verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_scopes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    initiated_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_oauth_states_user_id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SocialPostMedia(TimestampMixin, Base):
    __tablename__ = "social_post_media"
    __table_args__ = (
        UniqueConstraint("public_media_token", name="uq_spm_public_token"),
        Index("ix_spm_post_order", "social_post_id", "sort_order"),
        Index("ix_spm_asset", "media_asset_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    social_post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("social_posts.id", name="fk_spm_post_id", ondelete="CASCADE"),
        nullable=False,
    )
    media_asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("media_assets.id", name="fk_spm_media_asset_id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    role: Mapped[str] = mapped_column(
        String(24), nullable=False, default="primary", server_default="primary"
    )
    alt_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_prepared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    prepared_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prepared_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prepared_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prepared_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prepared_file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    public_media_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    public_media_expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class PublishingSchedule(TimestampMixin, Base):
    __tablename__ = "publishing_schedules"
    __table_args__ = (
        Index("ix_pub_sched_window", "status", "scheduled_at"),
        Index("ix_pub_sched_site", "website_id", "scheduled_at"),
        Index("ix_pub_sched_post", "social_post_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_pub_sched_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    social_profile_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("social_profiles.id", name="fk_pub_sched_profile_id", ondelete="SET NULL"),
        nullable=True,
    )
    social_post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("social_posts.id", name="fk_pub_sched_post_id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Manila", server_default="Asia/Manila"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="scheduled", server_default="scheduled"
    )
    rescheduled_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_pub_sched_created_by", ondelete="SET NULL"),
        nullable=True,
    )


class PublishingJob(TimestampMixin, Base):
    __tablename__ = "publishing_jobs"
    __table_args__ = (
        UniqueConstraint("job_uuid", name="uq_pub_jobs_uuid"),
        UniqueConstraint("idempotency_key", name="uq_pub_jobs_idempotency"),
        Index("ix_pub_jobs_dedupe", "publish_dedupe_key"),
        Index("ix_pub_jobs_claim", "status", "available_at", "id"),
        Index("ix_pub_jobs_stale", "status", "heartbeat_at"),
        Index("ix_pub_jobs_post", "social_post_id", "status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    publish_dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_pub_jobs_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    social_profile_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("social_profiles.id", name="fk_pub_jobs_profile_id", ondelete="SET NULL"),
        nullable=True,
    )
    social_post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("social_posts.id", name="fk_pub_jobs_post_id", ondelete="CASCADE"),
        nullable=False,
    )
    publishing_schedule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "publishing_schedules.id", name="fk_pub_jobs_schedule_id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    approved_revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    publishing_method: Mapped[str] = mapped_column(
        String(24), nullable=False, default="api", server_default="api"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=utc_now_naive
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    requires_verification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    paused_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_pub_jobs_created_by", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class PublishingLog(Base):
    __tablename__ = "publishing_logs"
    __table_args__ = (
        Index("ix_pub_logs_post", "social_post_id", "created_at"),
        Index("ix_pub_logs_job", "publishing_job_id"),
        Index("ix_pub_logs_website_created", "website_id", "created_at"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    publishing_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("publishing_jobs.id", name="fk_pub_logs_job_id", ondelete="SET NULL"),
        nullable=True,
    )
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_pub_logs_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    social_profile_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("social_profiles.id", name="fk_pub_logs_profile_id", ondelete="SET NULL"),
        nullable=True,
    )
    social_post_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("social_posts.id", name="fk_pub_logs_post_id", ondelete="SET NULL"),
        nullable=True,
    )
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    response_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_pub_logs_user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PublicationRecord(TimestampMixin, Base):
    __tablename__ = "publication_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_pub_rec_idempotency"),
        Index("ix_pub_rec_site_date", "website_id", "published_at"),
        Index("ix_pub_rec_platform_outcome", "platform_key", "outcome", "published_at"),
        Index("ix_pub_rec_post", "social_post_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_pub_rec_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    website_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    social_profile_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("social_profiles.id", name="fk_pub_rec_profile_id", ondelete="SET NULL"),
        nullable=True,
    )
    profile_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    platform_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platforms.id", name="fk_pub_rec_platform_id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    platform_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    social_post_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("social_posts.id", name="fk_pub_rec_post_id", ondelete="SET NULL"),
        nullable=True,
    )
    website_content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("website_contents.id", name="fk_pub_rec_content_id", ondelete="SET NULL"),
        nullable=True,
    )
    source_title_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    approved_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publishing_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("publishing_jobs.id", name="fk_pub_rec_job_id", ondelete="SET NULL"),
        nullable=True,
    )
    publishing_method: Mapped[str] = mapped_column(
        String(24), nullable=False, default="api", server_default="api"
    )
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified", server_default="unverified"
    )
    outcome: Mapped[str] = mapped_column(
        String(32), nullable=False, default="published", server_default="published"
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    caption_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags_snapshot_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_pub_rec_recorded_by", ondelete="SET NULL"),
        nullable=True,
    )
