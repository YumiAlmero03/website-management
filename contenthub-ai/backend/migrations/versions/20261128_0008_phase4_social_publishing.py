"""Phase 4 social publishing, connections, OAuth PKCE state, media, schedules, jobs & history

Revision ID: 20261128_0008
Revises: 20261128_0007
Create Date: 2026-11-28 12:15:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.services.ai.defaults import DEFAULT_PLATFORMS

revision: str = "20261128_0008"
down_revision: str | None = "20261128_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    # 1. Extend social_profiles with Phase 4 publishing preferences & verification metadata
    op.add_column(
        "social_profiles",
        sa.Column(
            "publishing_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "social_profiles",
        sa.Column("display_timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("preferred_publishing_days", sa.JSON(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("preferred_publishing_times", sa.JSON(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("daily_publishing_limit", sa.Integer(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("min_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column(
            "require_approval_before_publish",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "social_profiles",
        sa.Column(
            "default_media_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "social_profiles",
        sa.Column("granted_permissions_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column(
            "publishing_eligibility_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "social_profiles",
        sa.Column("publishing_eligibility_reason", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("last_published_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "social_profiles",
        sa.Column("last_connection_error", sa.String(length=500), nullable=True),
    )

    # 2. Extend social_posts with publishing lifecycle, UTM, scheduling & publication outcomes
    op.add_column(
        "social_posts",
        sa.Column(
            "publishing_status",
            sa.String(length=32),
            nullable=False,
            server_default="unscheduled",
        ),
    )
    op.add_column(
        "social_posts",
        sa.Column("approved_revision_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("alternative_captions_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("utm_params_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("target_url_with_utm", sa.String(length=1200), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("display_timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("published_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("published_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column(
        "social_posts",
        sa.Column("last_publish_error", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "social_posts",
        sa.Column("last_publish_attempt_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_social_posts_publishing_status",
        "social_posts",
        ["publishing_status", "scheduled_for"],
    )
    op.create_index("ix_social_posts_published_at", "social_posts", ["published_at"])

    # 3. social_profile_connections
    op.create_table(
        "social_profile_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column(
            "connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_connected",
        ),
        sa.Column("account_type", sa.String(length=64), nullable=True),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("external_username", sa.String(length=255), nullable=True),
        sa.Column("external_display_name", sa.String(length=255), nullable=True),
        sa.Column("profile_url", sa.String(length=500), nullable=True),
        sa.Column("target_resource_id", sa.String(length=255), nullable=True),
        sa.Column("target_resource_name", sa.String(length=255), nullable=True),
        sa.Column("available_targets_json", sa.JSON(), nullable=False),
        sa.Column("granted_scopes_json", sa.JSON(), nullable=False),
        sa.Column("required_scopes_json", sa.JSON(), nullable=False),
        sa.Column("missing_scopes_json", sa.JSON(), nullable=False),
        sa.Column(
            "eligibility_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("eligibility_notes", sa.String(length=500), nullable=True),
        sa.Column("access_tier", sa.String(length=64), nullable=True),
        sa.Column(
            "allow_paid_publishing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("api_version", sa.String(length=32), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_spc_profile_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_spc_website_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name="fk_spc_platform_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("social_profile_id", name="uq_spc_profile_id"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_spc_website_status",
        "social_profile_connections",
        ["website_id", "connection_status"],
    )
    op.create_index("ix_spc_expires", "social_profile_connections", ["token_expires_at"])

    # 4. oauth_state_sessions
    op.create_table(
        "oauth_state_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("encrypted_code_verifier", sa.Text(), nullable=True),
        sa.Column("requested_scopes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("initiated_by", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_oauth_states_website_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_oauth_states_profile_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by"],
            ["users.id"],
            name="fk_oauth_states_user_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("state_hash", name="uq_oauth_states_hash"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_oauth_states_profile_status",
        "oauth_state_sessions",
        ["social_profile_id", "status"],
    )

    # 5. social_post_media
    op.create_table(
        "social_post_media",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("social_post_id", sa.BigInteger(), nullable=False),
        sa.Column("media_asset_id", sa.BigInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="primary"),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("is_prepared", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("prepared_file_path", sa.String(length=500), nullable=True),
        sa.Column("prepared_mime_type", sa.String(length=100), nullable=True),
        sa.Column("prepared_width", sa.Integer(), nullable=True),
        sa.Column("prepared_height", sa.Integer(), nullable=True),
        sa.Column("prepared_file_size", sa.BigInteger(), nullable=True),
        sa.Column("public_media_token", sa.String(length=64), nullable=True),
        sa.Column("public_media_expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["social_post_id"],
            ["social_posts.id"],
            name="fk_spm_post_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_spm_media_asset_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("public_media_token", name="uq_spm_public_token"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_spm_post_order", "social_post_media", ["social_post_id", "sort_order"])
    op.create_index("ix_spm_asset", "social_post_media", ["media_asset_id"])

    # 6. publishing_schedules
    op.create_table(
        "publishing_schedules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("social_post_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("approved_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column(
            "display_timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Manila",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("rescheduled_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_pub_sched_website_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_pub_sched_profile_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["social_post_id"],
            ["social_posts.id"],
            name="fk_pub_sched_post_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_pub_sched_created_by",
            ondelete="SET NULL",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_pub_sched_window", "publishing_schedules", ["status", "scheduled_at"])
    op.create_index("ix_pub_sched_site", "publishing_schedules", ["website_id", "scheduled_at"])
    op.create_index("ix_pub_sched_post", "publishing_schedules", ["social_post_id"])

    # 7. publishing_jobs
    op.create_table(
        "publishing_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_uuid", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("publish_dedupe_key", sa.String(length=64), nullable=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("social_post_id", sa.BigInteger(), nullable=False),
        sa.Column("publishing_schedule_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("publishing_method", sa.String(length=24), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column(
            "requires_verification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("published_url", sa.String(length=1000), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("paused_reason", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_pub_jobs_website_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_pub_jobs_profile_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["social_post_id"],
            ["social_posts.id"],
            name="fk_pub_jobs_post_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["publishing_schedule_id"],
            ["publishing_schedules.id"],
            name="fk_pub_jobs_schedule_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_pub_jobs_created_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("job_uuid", name="uq_pub_jobs_uuid"),
        sa.UniqueConstraint("idempotency_key", name="uq_pub_jobs_idempotency"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_pub_jobs_dedupe", "publishing_jobs", ["publish_dedupe_key"])
    op.create_index("ix_pub_jobs_claim", "publishing_jobs", ["status", "available_at", "id"])
    op.create_index("ix_pub_jobs_stale", "publishing_jobs", ["status", "heartbeat_at"])
    op.create_index("ix_pub_jobs_post", "publishing_jobs", ["social_post_id", "status"])

    # 8. publishing_logs
    op.create_table(
        "publishing_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("publishing_job_id", sa.BigInteger(), nullable=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("social_post_id", sa.BigInteger(), nullable=True),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("published_url", sa.String(length=1000), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("response_summary_json", sa.JSON(), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["publishing_job_id"],
            ["publishing_jobs.id"],
            name="fk_pub_logs_job_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_pub_logs_website_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_pub_logs_profile_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["social_post_id"],
            ["social_posts.id"],
            name="fk_pub_logs_post_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_pub_logs_user_id",
            ondelete="SET NULL",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_pub_logs_post", "publishing_logs", ["social_post_id", "created_at"])
    op.create_index("ix_pub_logs_job", "publishing_logs", ["publishing_job_id"])
    op.create_index("ix_pub_logs_website_created", "publishing_logs", ["website_id", "created_at"])

    # 9. publication_records
    op.create_table(
        "publication_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("profile_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("platform_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("platform_display_name", sa.String(length=100), nullable=False),
        sa.Column("social_post_id", sa.BigInteger(), nullable=True),
        sa.Column("website_content_id", sa.BigInteger(), nullable=True),
        sa.Column("source_title_snapshot", sa.String(length=500), nullable=True),
        sa.Column("approved_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_version_number", sa.Integer(), nullable=True),
        sa.Column("publishing_job_id", sa.BigInteger(), nullable=True),
        sa.Column("publishing_method", sa.String(length=24), nullable=False, server_default="api"),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False, server_default="published"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("published_url", sa.String(length=1000), nullable=True),
        sa.Column("caption_snapshot", sa.Text(), nullable=True),
        sa.Column("hashtags_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("recorded_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_pub_rec_website_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_pub_rec_profile_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name="fk_pub_rec_platform_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_post_id"],
            ["social_posts.id"],
            name="fk_pub_rec_post_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_pub_rec_content_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["publishing_job_id"],
            ["publishing_jobs.id"],
            name="fk_pub_rec_job_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name="fk_pub_rec_recorded_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_pub_rec_idempotency"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_pub_rec_site_date", "publication_records", ["website_id", "published_at"]
    )
    op.create_index(
        "ix_pub_rec_platform_outcome",
        "publication_records",
        ["platform_key", "outcome", "published_at"],
    )
    op.create_index("ix_pub_rec_post", "publication_records", ["social_post_id"])

    # 10. Sync platforms capability definitions and backfill existing Phase 3 rows cleanly
    conn = op.get_bind()
    for p in DEFAULT_PLATFORMS:
        conn.execute(
            sa.text(
                "UPDATE platforms "
                "SET supports_free_auto_publish = :free_pub, "
                "credential_fields_json = :cred_fields, "
                "capabilities_json = :caps "
                "WHERE platform_key = :pkey"
            ),
            {
                "free_pub": 1 if p["supports_free_auto_publish"] else 0,
                "cred_fields": json.dumps(list(p["credential_fields_json"])),
                "caps": json.dumps(dict(p["capabilities_json"])),
                "pkey": p["platform_key"],
            },
        )

    conn.execute(
        sa.text(
            "UPDATE social_profiles "
            "SET publishing_eligibility_status = 'manual_only' "
            "WHERE publishing_method = 'manual'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE social_posts SET publishing_status = CASE "
            "WHEN status = 'approved' THEN 'approved' "
            "WHEN status = 'pending_review' THEN 'pending_approval' "
            "WHEN status = 'archived' THEN 'archived' "
            "ELSE 'unscheduled' END"
        )
    )


def downgrade() -> None:
    # Dropping tables directly automatically drops their indexes and FK constraints in MySQL.
    op.drop_table("publication_records")
    op.drop_table("publishing_logs")
    op.drop_table("publishing_jobs")
    op.drop_table("publishing_schedules")
    op.drop_table("social_post_media")
    op.drop_table("oauth_state_sessions")
    op.drop_table("social_profile_connections")

    op.drop_index("ix_social_posts_published_at", table_name="social_posts")
    op.drop_index("ix_social_posts_publishing_status", table_name="social_posts")
    for col in (
        "last_publish_attempt_at",
        "last_publish_error",
        "verification_status",
        "published_url",
        "external_post_id",
        "published_at",
        "display_timezone",
        "scheduled_for",
        "target_url_with_utm",
        "utm_params_json",
        "alternative_captions_json",
        "approved_revision_id",
        "publishing_status",
    ):
        op.drop_column("social_posts", col)

    for col in (
        "last_connection_error",
        "last_published_at",
        "last_verified_at",
        "publishing_eligibility_reason",
        "publishing_eligibility_status",
        "granted_permissions_json",
        "default_media_required",
        "require_approval_before_publish",
        "min_interval_minutes",
        "daily_publishing_limit",
        "preferred_publishing_times",
        "preferred_publishing_days",
        "display_timezone",
        "publishing_enabled",
    ):
        op.drop_column("social_profiles", col)
