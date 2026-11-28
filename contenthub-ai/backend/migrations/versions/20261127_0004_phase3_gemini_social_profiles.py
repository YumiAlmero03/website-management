"""Phase 3 Gemini AI engine, website knowledge profiles, prompts, cache, social profiles, and draft management

Revision ID: 20261127_0004
Revises: 20261127_0003
Create Date: 2026-11-27 17:10:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.services.ai.defaults import DEFAULT_PLATFORMS, DEFAULT_PROMPT_TEMPLATES

revision: str = "20261127_0004"
down_revision: str | None = "20261127_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    # Add Phase 3 auto-generation policy columns to websites
    op.add_column(
        "websites",
        sa.Column(
            "auto_generate_require_published_at",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "websites",
        sa.Column(
            "auto_generate_context_mode",
            sa.String(length=32),
            nullable=False,
            server_default="optimized",
        ),
    )

    # 1. platforms
    op.create_table(
        "platforms",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="social"),
        sa.Column("default_max_chars", sa.Integer(), nullable=True),
        sa.Column("url_counts_as_chars", sa.Integer(), nullable=True),
        sa.Column("supports_hashtags", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("supports_cta", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("supports_source_url", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("supports_title", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("supports_media", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "supports_free_auto_publish",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("credential_fields_json", sa.JSON(), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
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
        sa.UniqueConstraint("platform_key", name="uq_platforms_platform_key"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_platforms_sort_enabled", "platforms", ["is_enabled", "sort_order"])

    # 2. social_profiles
    op.create_table(
        "social_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_name", sa.String(length=150), nullable=False),
        sa.Column("profile_url", sa.String(length=500), nullable=True),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("profile_image_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("publishing_method", sa.String(length=24), nullable=False, server_default="manual"),
        sa.Column(
            "credential_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_configured",
        ),
        sa.Column("generation_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "automatic_generation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("auto_publish_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("custom_language", sa.String(length=32), nullable=True),
        sa.Column("writing_tone", sa.String(length=120), nullable=True),
        sa.Column("platform_ai_instructions", sa.Text(), nullable=True),
        sa.Column("default_hashtags", sa.JSON(), nullable=True),
        sa.Column("default_cta", sa.String(length=255), nullable=True),
        sa.Column("preferred_length", sa.String(length=32), nullable=True),
        sa.Column("character_limit", sa.Integer(), nullable=True),
        sa.Column("include_source_url", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("include_hashtags", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("include_emojis", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("content_restrictions", sa.Text(), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("encrypted_api_secret", sa.Text(), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("encrypted_app_id", sa.Text(), nullable=True),
        sa.Column("encrypted_app_secret", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("credentials_updated_at", sa.DateTime(), nullable=True),
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
            ["website_id"], ["websites.id"], name="fk_social_profiles_website_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name="fk_social_profiles_platform_id",
            ondelete="RESTRICT",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_social_profiles_website_active", "social_profiles", ["website_id", "is_active"])
    op.create_index("ix_social_profiles_website_platform", "social_profiles", ["website_id", "platform_id"])
    op.create_index(
        "ix_social_profiles_generation",
        "social_profiles",
        ["website_id", "is_active", "generation_enabled"],
    )

    # 3. ai_providers
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False, server_default="gemini"),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column(
            "selected_model",
            sa.String(length=120),
            nullable=False,
            server_default="gemini-3.5-flash-lite",
        ),
        sa.Column("available_models_json", sa.JSON(), nullable=True),
        sa.Column("default_temperature", sa.Float(), nullable=False, server_default=sa.text("0.4")),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default=sa.text("1500")),
        sa.Column(
            "request_timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("45")
        ),
        sa.Column("max_retry_attempts", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column(
            "daily_request_limit", sa.Integer(), nullable=False, server_default=sa.text("100")
        ),
        sa.Column(
            "daily_token_limit", sa.Integer(), nullable=False, server_default=sa.text("250000")
        ),
        sa.Column(
            "per_minute_request_limit", sa.Integer(), nullable=False, server_default=sa.text("10")
        ),
        sa.Column("generation_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "response_caching_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "token_optimization_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("allow_paid_fallback", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_test_status", sa.String(length=32), nullable=False, server_default="untested"),
        sa.Column("last_test_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_test_error", sa.String(length=500), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
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
        sa.UniqueConstraint("name", name="uq_ai_providers_name"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_ai_providers_default_active", "ai_providers", ["is_default", "is_active"])

    # 4. website_knowledge_profiles & revisions
    op.create_table(
        "website_knowledge_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("brand_name", sa.String(length=150), nullable=False),
        sa.Column("brand_description", sa.Text(), nullable=True),
        sa.Column("website_category", sa.String(length=100), nullable=True),
        sa.Column("business_overview", sa.Text(), nullable=True),
        sa.Column("products_and_services", sa.JSON(), nullable=False),
        sa.Column("main_features", sa.JSON(), nullable=False),
        sa.Column("target_audience", sa.String(length=255), nullable=True),
        sa.Column("target_country", sa.String(length=64), nullable=True),
        sa.Column("primary_language", sa.String(length=32), nullable=False, server_default="en"),
        sa.Column("secondary_languages", sa.JSON(), nullable=False),
        sa.Column("recommended_writing_tone", sa.String(length=120), nullable=True),
        sa.Column("main_keywords", sa.JSON(), nullable=False),
        sa.Column("content_pillars", sa.JSON(), nullable=False),
        sa.Column("important_internal_links", sa.JSON(), nullable=False),
        sa.Column("relevant_publishing_restrictions", sa.Text(), nullable=True),
        sa.Column("source_content_references", sa.JSON(), nullable=False),
        sa.Column("administrator_notes", sa.Text(), nullable=True),
        sa.Column("manual_overrides_json", sa.JSON(), nullable=False),
        sa.Column("field_provenance_json", sa.JSON(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_generated_at", sa.DateTime(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
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
            name="fk_knowledge_profiles_website_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_knowledge_profiles_approved_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("website_id", name="uq_website_knowledge_profiles_website"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_website_knowledge_profiles_status", "website_knowledge_profiles", ["status"])

    op.create_table(
        "website_knowledge_profile_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("knowledge_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("change_source", sa.String(length=32), nullable=False, server_default="generated"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_profile_id"],
            ["website_knowledge_profiles.id"],
            name="fk_knowledge_rev_profile_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_knowledge_rev_website_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_knowledge_rev_created_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "knowledge_profile_id",
            "profile_version",
            name="uq_knowledge_profile_revisions_ver",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_knowledge_profile_revisions_website",
        "website_knowledge_profile_revisions",
        ["website_id", "created_at"],
    )

    # 5. prompt_templates & revisions
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("scope_key", sa.String(length=120), nullable=False, server_default="global"),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=True),
        sa.Column("website_id", sa.BigInteger(), nullable=True),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("system_instructions", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("available_variables_json", sa.JSON(), nullable=False),
        sa.Column("response_schema_name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_system_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
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
            name="fk_prompt_templates_website_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_prompt_templates_social_profile_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("template_key", "scope_key", name="uq_prompt_templates_key_scope"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_prompt_templates_task_platform",
        "prompt_templates",
        ["task_type", "platform_key", "is_active"],
    )
    op.create_index("ix_prompt_templates_website", "prompt_templates", ["website_id"])
    op.create_index(
        "ix_prompt_templates_social_profile", "prompt_templates", ["social_profile_id"]
    )

    op.create_table(
        "prompt_template_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("prompt_template_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_instructions", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("change_note", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_prompt_template_revs_template_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_prompt_template_revs_created_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "prompt_template_id", "version", name="uq_prompt_template_revs_ver"
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_prompt_template_revs_tpl", "prompt_template_revisions", ["prompt_template_id"]
    )

    # 6. ai_response_cache
    op.create_table(
        "ai_response_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("cache_key_hash", sa.String(length=64), nullable=False),
        sa.Column("ai_provider_id", sa.BigInteger(), nullable=False),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_content_id", sa.BigInteger(), nullable=True),
        sa.Column("prompt_template_id", sa.BigInteger(), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("context_mode", sa.String(length=32), nullable=False, server_default="optimized"),
        sa.Column("language", sa.String(length=32), nullable=False, server_default="en"),
        sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_config_hash", sa.String(length=64), nullable=False),
        sa.Column("generation_settings_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_hit_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_provider_id"],
            ["ai_providers.id"],
            name="fk_ai_cache_provider_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"], ["websites.id"], name="fk_ai_cache_website_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_ai_cache_content_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_ai_cache_prompt_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("cache_key_hash", name="uq_ai_response_cache_key_hash"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_ai_response_cache_website", "ai_response_cache", ["website_id", "task_type"])
    op.create_index("ix_ai_response_cache_expires_at", "ai_response_cache", ["expires_at"])
    op.create_index("ix_ai_response_cache_source_hash", "ai_response_cache", ["source_content_hash"])

    # 7. ai_generation_jobs
    op.create_table(
        "ai_generation_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "job_type", sa.String(length=48), nullable=False, server_default="social_generation"
        ),
        sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_content_id", sa.BigInteger(), nullable=True),
        sa.Column("target_profile_ids_json", sa.JSON(), nullable=False),
        sa.Column("ai_provider_id", sa.BigInteger(), nullable=True),
        sa.Column("prompt_template_id", sa.BigInteger(), nullable=True),
        sa.Column("context_mode", sa.String(length=32), nullable=False, server_default="optimized"),
        sa.Column("force_regenerate", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("regenerate_social_post_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("defer_reason", sa.String(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("result_summary_json", sa.JSON(), nullable=True),
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
            ["website_id"], ["websites.id"], name="fk_ai_jobs_website_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_ai_jobs_content_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ai_provider_id"],
            ["ai_providers.id"],
            name="fk_ai_jobs_provider_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_ai_jobs_prompt_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_ai_jobs_created_by", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("job_uuid", name="uq_ai_generation_jobs_uuid"),
        sa.UniqueConstraint("idempotency_key", name="uq_ai_generation_jobs_idempotency"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_ai_generation_jobs_claim", "ai_generation_jobs", ["status", "next_retry_at", "id"])
    op.create_index("ix_ai_generation_jobs_stale", "ai_generation_jobs", ["status", "heartbeat_at"])
    op.create_index(
        "ix_ai_generation_jobs_website_content",
        "ai_generation_jobs",
        ["website_id", "website_content_id"],
    )

    # 8. ai_generation_logs
    op.create_table(
        "ai_generation_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("ai_provider_id", sa.BigInteger(), nullable=False),
        sa.Column("prompt_template_id", sa.BigInteger(), nullable=True),
        sa.Column("website_id", sa.BigInteger(), nullable=True),
        sa.Column("website_content_id", sa.BigInteger(), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("context_mode", sa.String(length=32), nullable=False, server_default="optimized"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("cache_key_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=True),
        sa.Column("measured_input_tokens", sa.Integer(), nullable=True),
        sa.Column("measured_output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_measured_tokens", sa.Integer(), nullable=True),
        sa.Column("token_usage_status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("truncated_input", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("truncation_note", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["ai_generation_jobs.id"], name="fk_ai_logs_job_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["ai_provider_id"],
            ["ai_providers.id"],
            name="fk_ai_logs_provider_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_ai_logs_prompt_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"], ["websites.id"], name="fk_ai_logs_website_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_ai_logs_content_id",
            ondelete="SET NULL",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_ai_generation_logs_created", "ai_generation_logs", ["created_at"])
    op.create_index(
        "ix_ai_generation_logs_provider_created",
        "ai_generation_logs",
        ["ai_provider_id", "created_at"],
    )
    op.create_index(
        "ix_ai_generation_logs_website_created", "ai_generation_logs", ["website_id", "created_at"]
    )
    op.create_index("ix_ai_generation_logs_status", "ai_generation_logs", ["status", "created_at"])

    # 9. social_posts & revisions
    op.create_table(
        "social_posts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_content_id", sa.BigInteger(), nullable=True),
        sa.Column("social_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_id", sa.BigInteger(), nullable=False),
        sa.Column("featured_media_id", sa.BigInteger(), nullable=True),
        sa.Column("ai_generation_job_id", sa.BigInteger(), nullable=True),
        sa.Column("ai_provider_id", sa.BigInteger(), nullable=True),
        sa.Column("generation_model", sa.String(length=120), nullable=True),
        sa.Column("prompt_template_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("assembled_content", sa.Text(), nullable=False),
        sa.Column("hashtags_json", sa.JSON(), nullable=False),
        sa.Column("cta_text", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=False, server_default="en"),
        sa.Column("character_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("character_limit", sa.Integer(), nullable=True),
        sa.Column("validation_warnings_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_review"),
        sa.Column("is_manually_edited", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("dedupe_key", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.BigInteger(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
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
            ["website_id"], ["websites.id"], name="fk_social_posts_website_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_social_posts_content_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["social_profile_id"],
            ["social_profiles.id"],
            name="fk_social_posts_social_profile_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"], ["platforms.id"], name="fk_social_posts_platform_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["featured_media_id"],
            ["media_assets.id"],
            name="fk_social_posts_media_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ai_generation_job_id"],
            ["ai_generation_jobs.id"],
            name="fk_social_posts_job_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ai_provider_id"],
            ["ai_providers.id"],
            name="fk_social_posts_provider_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_social_posts_prompt_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name="fk_social_posts_approved_by", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by"], ["users.id"], name="fk_social_posts_rejected_by", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_social_posts_dedupe_key"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_social_posts_status", "social_posts", ["status", "created_at"])
    op.create_index(
        "ix_social_posts_website_profile", "social_posts", ["website_id", "social_profile_id"]
    )
    op.create_index("ix_social_posts_content", "social_posts", ["website_content_id"])
    op.create_index("ix_social_posts_platform", "social_posts", ["platform_id"])

    op.create_table(
        "social_post_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("social_post_id", sa.BigInteger(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("assembled_content", sa.Text(), nullable=False),
        sa.Column("hashtags_json", sa.JSON(), nullable=False),
        sa.Column("cta_text", sa.String(length=255), nullable=True),
        sa.Column("generation_model", sa.String(length=120), nullable=True),
        sa.Column(
            "change_type", sa.String(length=32), nullable=False, server_default="initial_generated"
        ),
        sa.Column("edited_by", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["social_post_id"],
            ["social_posts.id"],
            name="fk_social_post_revs_post_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by"], ["users.id"], name="fk_social_post_revs_edited_by", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("social_post_id", "version_number", name="uq_social_post_revs_ver"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_social_post_revs_post", "social_post_revisions", ["social_post_id"])

    # Seed configurable platform catalog and global default prompt templates safely via bulk_insert
    platforms_tbl = sa.table(
        "platforms",
        sa.column("platform_key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("default_max_chars", sa.Integer()),
        sa.column("url_counts_as_chars", sa.Integer()),
        sa.column("supports_hashtags", sa.Boolean()),
        sa.column("supports_cta", sa.Boolean()),
        sa.column("supports_source_url", sa.Boolean()),
        sa.column("supports_title", sa.Boolean()),
        sa.column("supports_media", sa.Boolean()),
        sa.column("supports_free_auto_publish", sa.Boolean()),
        sa.column("credential_fields_json", sa.Text()),
        sa.column("capabilities_json", sa.Text()),
        sa.column("is_enabled", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        platforms_tbl,
        [
            {
                "platform_key": p["platform_key"],
                "display_name": p["display_name"],
                "category": p["category"],
                "default_max_chars": p["default_max_chars"],
                "url_counts_as_chars": p["url_counts_as_chars"],
                "supports_hashtags": bool(p["supports_hashtags"]),
                "supports_cta": bool(p["supports_cta"]),
                "supports_source_url": bool(p["supports_source_url"]),
                "supports_title": bool(p["supports_title"]),
                "supports_media": bool(p["supports_media"]),
                "supports_free_auto_publish": bool(p["supports_free_auto_publish"]),
                "credential_fields_json": json.dumps(list(p["credential_fields_json"])),
                "capabilities_json": json.dumps(dict(p["capabilities_json"])),
                "is_enabled": True,
                "sort_order": int(p["sort_order"]),
            }
            for p in DEFAULT_PLATFORMS
        ],
    )

    prompts_tbl = sa.table(
        "prompt_templates",
        sa.column("template_key", sa.String()),
        sa.column("scope_key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("task_type", sa.String()),
        sa.column("platform_key", sa.String()),
        sa.column("system_instructions", sa.Text()),
        sa.column("user_prompt_template", sa.Text()),
        sa.column("available_variables_json", sa.Text()),
        sa.column("response_schema_name", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_system_default", sa.Boolean()),
    )
    op.bulk_insert(
        prompts_tbl,
        [
            {
                "template_key": tpl["template_key"],
                "scope_key": "global",
                "name": tpl["name"],
                "task_type": tpl["task_type"],
                "platform_key": tpl["platform_key"],
                "system_instructions": tpl["system_instructions"],
                "user_prompt_template": tpl["user_prompt_template"],
                "available_variables_json": json.dumps(list(tpl["available_variables_json"])),
                "response_schema_name": tpl["response_schema_name"],
                "version": int(tpl["version"]),
                "is_active": bool(tpl["is_active"]),
                "is_system_default": bool(tpl["is_system_default"]),
            }
            for tpl in DEFAULT_PROMPT_TEMPLATES
        ],
    )


def downgrade() -> None:
    op.drop_table("social_post_revisions")
    op.drop_table("social_posts")
    op.drop_table("ai_generation_logs")
    op.drop_table("ai_generation_jobs")
    op.drop_table("ai_response_cache")
    op.drop_table("prompt_template_revisions")
    op.drop_table("prompt_templates")
    op.drop_table("website_knowledge_profile_revisions")
    op.drop_table("website_knowledge_profiles")
    op.drop_table("ai_providers")
    op.drop_table("social_profiles")
    op.drop_table("platforms")
    op.drop_column("websites", "auto_generate_context_mode")
    op.drop_column("websites", "auto_generate_require_published_at")
