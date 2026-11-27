"""Phase 2 website monitoring tables (brands, media_assets, websites, source_articles, source_article_revisions, website_scan_logs)

Revision ID: 20261126_0002
Revises: 20261126_0001
Create Date: 2026-11-26 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261126_0002"
down_revision: str | None = "20261126_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.String(length=255), nullable=True),
        sa.Column("target_country", sa.String(length=64), nullable=True),
        sa.Column("primary_language", sa.String(length=32), nullable=False, server_default="en"),
        sa.Column("secondary_languages", sa.JSON(), nullable=True),
        sa.Column("tone", sa.String(length=120), nullable=True),
        sa.Column("target_keywords", sa.JSON(), nullable=True),
        sa.Column("restricted_keywords", sa.JSON(), nullable=True),
        sa.Column("default_hashtags", sa.JSON(), nullable=True),
        sa.Column("default_cta", sa.String(length=255), nullable=True),
        sa.Column("writing_guidelines", sa.Text(), nullable=True),
        sa.Column("ai_instructions", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
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
        sa.UniqueConstraint("slug", name="uq_brands_slug"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_brands_is_active", "brands", ["is_active"])

    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("brand_id", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name="fk_media_assets_brand_id_brands",
            ondelete="SET NULL",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_media_assets_brand_id", "media_assets", ["brand_id"])
    op.create_index("ix_media_assets_checksum", "media_assets", ["checksum"])

    op.create_table(
        "websites",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("website_type", sa.String(length=32), nullable=False, server_default="wordpress"),
        sa.Column("discovery_method", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("rss_url", sa.String(length=500), nullable=True),
        sa.Column("sitemap_url", sa.String(length=500), nullable=True),
        sa.Column("llms_url", sa.String(length=500), nullable=True),
        sa.Column("api_endpoint", sa.String(length=500), nullable=True),
        sa.Column("article_url_patterns", sa.JSON(), nullable=True),
        sa.Column("excluded_url_patterns", sa.JSON(), nullable=True),
        sa.Column(
            "scan_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("360"),
        ),
        sa.Column("auto_scan", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("auto_generate", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "initial_scan_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "baseline_mode",
            sa.String(length=32),
            nullable=False,
            server_default="import_existing",
        ),
        sa.Column("baseline_after_date", sa.DateTime(), nullable=True),
        sa.Column("baseline_limit", sa.Integer(), nullable=True),
        sa.Column("last_etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified_header", sa.String(length=128), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(), nullable=True),
        sa.Column("last_successful_scan_at", sa.DateTime(), nullable=True),
        sa.Column("next_scan_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
            ["brand_id"],
            ["brands.id"],
            name="fk_websites_brand_id_brands",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("brand_id", "domain", name="uq_websites_brand_domain"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_websites_brand_id", "websites", ["brand_id"])
    op.create_index("ix_websites_domain", "websites", ["domain"])
    op.create_index("ix_websites_status", "websites", ["status"])
    op.create_index("ix_websites_next_scan_at", "websites", ["next_scan_at"])

    op.create_table(
        "source_articles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("featured_media_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("canonical_url", sa.String(length=1000), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("author", sa.String(length=150), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column(
            "original_content",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column(
            "markdown_content",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column(
            "optimized_context",
            sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="extracted"),
        sa.Column(
            "is_historical_baseline",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("near_duplicate_of_id", sa.BigInteger(), nullable=True),
        sa.Column("near_duplicate_score", sa.Float(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_checked_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
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
            name="fk_source_articles_website_id_websites",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["featured_media_id"],
            ["media_assets.id"],
            name="fk_source_articles_featured_media_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["near_duplicate_of_id"],
            ["source_articles.id"],
            name="fk_source_articles_near_duplicate_of_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "website_id",
            "url_hash",
            name="uq_source_articles_website_url_hash",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_source_articles_website_id", "source_articles", ["website_id"])
    op.create_index("ix_source_articles_content_hash", "source_articles", ["content_hash"])
    op.create_index("ix_source_articles_published_at", "source_articles", ["published_at"])
    op.create_index("ix_source_articles_status", "source_articles", ["status"])
    op.create_index(
        "ft_source_articles_search",
        "source_articles",
        ["title", "meta_description", "markdown_content"],
        mysql_prefix="FULLTEXT",
    )

    op.create_table(
        "source_article_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column(
            "markdown_content",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["source_articles.id"],
            name="fk_source_article_revisions_article_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "article_id",
            "revision_number",
            name="uq_source_article_revisions_article_rev",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_source_article_revisions_article_id",
        "source_article_revisions",
        ["article_id"],
    )

    op.create_table(
        "website_scan_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("scan_method", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("urls_found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("articles_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_articles", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_articles", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unchanged_articles", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_articles", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_articles", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_website_scan_logs_website_id_websites",
            ondelete="CASCADE",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_website_scan_logs_website_started",
        "website_scan_logs",
        ["website_id", "started_at"],
    )
    op.create_index("ix_website_scan_logs_status", "website_scan_logs", ["status"])


def downgrade() -> None:
    op.drop_table("website_scan_logs")
    op.drop_table("source_article_revisions")
    op.drop_table("source_articles")
    op.drop_table("websites")
    op.drop_table("media_assets")
    op.drop_table("brands")
