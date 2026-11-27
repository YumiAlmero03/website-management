"""Phase 2.1 website-centric merge, custom categories, discovery sources, URL rules, and universal website contents

Revision ID: 20261127_0003
Revises: 20261126_0002
Create Date: 2026-11-27 15:30:00.000000
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from app.services.scanner.classifier import classify_url

revision: str = "20261127_0003"
down_revision: str | None = "20261126_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

DEFAULT_WEBSITE_CATEGORIES: tuple[tuple[str, str, str, int], ...] = (
    ("Sports Web", "sports-web", "Sports news, stats, teams, and betting editorial portals", 10),
    ("Casino", "casino", "Online casino, slots, live dealer, and gaming brands", 20),
    ("Brand", "brand", "Primary corporate or branded informational properties", 30),
    (
        "Illegal Brand",
        "illegal-brand",
        "User-labeled restricted/high-risk brand classification tag",
        40,
    ),
    ("Technology", "technology", "Software, SaaS, developer tools, and tech media", 50),
    ("E-commerce", "e-commerce", "Online stores, product catalogs, and retail sites", 60),
    ("News", "news", "Editorial newsrooms, magazines, and journalism portals", 70),
    ("Other", "other", "General or uncategorized websites", 80),
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Safety check: abort cleanly instead of merging/deleting if duplicate domains exist.
    dup_rows = conn.execute(
        sa.text(
            "SELECT domain, GROUP_CONCAT(id ORDER BY id) AS ids "
            "FROM websites GROUP BY domain HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if dup_rows:
        details = "; ".join(f"{r[0]} (website ids: {r[1]})" for r in dup_rows)
        raise RuntimeError(
            "Cannot migrate websites to unique domain ownership because multiple websites share "
            f"the same domain: {details}. Resolve duplicate domains explicitly before migrating."
        )

    # 2. Create website_categories and seed editable starter categories.
    op.create_table(
        "website_categories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.UniqueConstraint("slug", name="uq_website_categories_slug"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_website_categories_archived",
        "website_categories",
        ["is_archived", "sort_order"],
    )

    for name, slug, description, sort_order in DEFAULT_WEBSITE_CATEGORIES:
        conn.execute(
            sa.text(
                "INSERT INTO website_categories (name, slug, description, is_archived, sort_order) "
                "VALUES (:name, :slug, :desc, 0, :sort_order)"
            ),
            {"name": name, "slug": slug, "desc": description, "sort_order": sort_order},
        )

    # 3. Extend websites with merged brand identity, category FK, and batched crawl controls.
    op.add_column("websites", sa.Column("category_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "websites",
        sa.Column("brand_name", sa.String(length=150), nullable=False, server_default=""),
    )
    op.add_column("websites", sa.Column("brand_slug", sa.String(length=150), nullable=True))
    op.add_column("websites", sa.Column("logo_url", sa.String(length=500), nullable=True))
    op.add_column("websites", sa.Column("brand_description", sa.Text(), nullable=True))
    op.add_column("websites", sa.Column("target_audience", sa.String(length=255), nullable=True))
    op.add_column("websites", sa.Column("target_country", sa.String(length=64), nullable=True))
    op.add_column(
        "websites",
        sa.Column("primary_language", sa.String(length=32), nullable=False, server_default="en"),
    )
    op.add_column("websites", sa.Column("secondary_languages", sa.JSON(), nullable=True))
    op.add_column("websites", sa.Column("tone", sa.String(length=120), nullable=True))
    op.add_column("websites", sa.Column("target_keywords", sa.JSON(), nullable=True))
    op.add_column("websites", sa.Column("restricted_keywords", sa.JSON(), nullable=True))
    op.add_column("websites", sa.Column("default_hashtags", sa.JSON(), nullable=True))
    op.add_column("websites", sa.Column("default_cta", sa.String(length=255), nullable=True))
    op.add_column("websites", sa.Column("writing_guidelines", sa.Text(), nullable=True))
    op.add_column("websites", sa.Column("ai_instructions", sa.Text(), nullable=True))
    op.add_column(
        "websites",
        sa.Column("single_source_only", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "websites",
        sa.Column("crawl_batch_size", sa.Integer(), nullable=False, server_default=sa.text("100")),
    )
    op.add_column(
        "websites",
        sa.Column(
            "crawl_max_urls_per_run",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1000"),
        ),
    )

    op.create_index("ix_websites_category_id", "websites", ["category_id"])
    op.create_foreign_key(
        "fk_websites_category_id_categories",
        "websites",
        "website_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Copy all brand identity fields safely into each website before removing brands.
    conn.execute(
        sa.text(
            "UPDATE websites w "
            "JOIN brands b ON w.brand_id = b.id "
            "SET w.brand_name = b.name, "
            "    w.brand_slug = b.slug, "
            "    w.logo_url = b.logo_url, "
            "    w.brand_description = b.description, "
            "    w.target_audience = b.target_audience, "
            "    w.target_country = b.target_country, "
            "    w.primary_language = COALESCE(b.primary_language, 'en'), "
            "    w.secondary_languages = b.secondary_languages, "
            "    w.tone = b.tone, "
            "    w.target_keywords = b.target_keywords, "
            "    w.restricted_keywords = b.restricted_keywords, "
            "    w.default_hashtags = b.default_hashtags, "
            "    w.default_cta = b.default_cta, "
            "    w.writing_guidelines = b.writing_guidelines, "
            "    w.ai_instructions = b.ai_instructions"
        )
    )
    conn.execute(
        sa.text("UPDATE websites SET brand_name = name WHERE brand_name IS NULL OR brand_name = ''")
    )
    # Strip the legacy Phase 2 modal default taxonomy exclusions so Category/Tag/Archive URLs classify properly.
    legacy_taxonomy_defaults = {"/category/*", "/tag/*", "/author/*"}
    legacy_modal_defaults = {"/category/*", "/tag/*", "/author/*", "/wp-admin/*", "/search/*"}
    legacy_site_rows = conn.execute(
        sa.text("SELECT id, excluded_url_patterns FROM websites")
    ).fetchall()
    for wid, raw_exc in legacy_site_rows:
        exc_list = json.loads(raw_exc) if isinstance(raw_exc, str) else raw_exc
        if (
            isinstance(exc_list, list)
            and exc_list
            and set(exc_list).issubset(legacy_modal_defaults)
            and any(pat in legacy_taxonomy_defaults for pat in exc_list)
        ):
            cleaned_pats = [pat for pat in exc_list if pat not in legacy_taxonomy_defaults]
            conn.execute(
                sa.text("UPDATE websites SET excluded_url_patterns = :pats WHERE id = :wid"),
                {"pats": json.dumps(cleaned_pats), "wid": wid},
            )

    # 4. Migrate media_assets ownership from brand_id -> website_id cleanly.
    op.add_column("media_assets", sa.Column("website_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_media_assets_website_id", "media_assets", ["website_id"])
    op.create_foreign_key(
        "fk_media_assets_website_id_websites",
        "media_assets",
        "websites",
        ["website_id"],
        ["id"],
        ondelete="SET NULL",
    )
    conn.execute(
        sa.text(
            "UPDATE media_assets m "
            "JOIN ("
            "  SELECT featured_media_id, MIN(website_id) AS website_id "
            "  FROM source_articles WHERE featured_media_id IS NOT NULL "
            "  GROUP BY featured_media_id"
            ") sa ON m.id = sa.featured_media_id "
            "SET m.website_id = sa.website_id"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE media_assets m "
            "JOIN ("
            "  SELECT brand_id, MIN(id) AS website_id FROM websites GROUP BY brand_id"
            ") w ON m.brand_id = w.brand_id "
            "SET m.website_id = w.website_id "
            "WHERE m.website_id IS NULL AND m.brand_id IS NOT NULL"
        )
    )

    op.drop_constraint("fk_media_assets_brand_id_brands", "media_assets", type_="foreignkey")
    op.drop_index("ix_media_assets_brand_id", table_name="media_assets")
    op.drop_column("media_assets", "brand_id")

    # 5. Remove websites.brand_id and brands table after full verification/migration.
    op.drop_constraint("fk_websites_brand_id_brands", "websites", type_="foreignkey")
    op.drop_constraint("uq_websites_brand_domain", "websites", type_="unique")
    op.drop_index("ix_websites_brand_id", table_name="websites")
    op.drop_column("websites", "brand_id")
    op.create_unique_constraint("uq_websites_domain", "websites", ["domain"])

    op.drop_table("brands")

    # 6. Create website_discovery_sources (per-endpoint ETag, Last-Modified & health).
    op.create_table(
        "website_discovery_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_source_id", sa.BigInteger(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified_header", sa.String(length=128), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_urls_found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
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
            name="fk_wds_website_id_websites",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_source_id"],
            ["website_discovery_sources.id"],
            name="fk_wds_parent_source_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "website_id",
            "endpoint_hash",
            name="uq_website_discovery_sources_site_ep",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_website_discovery_sources_website_type",
        "website_discovery_sources",
        ["website_id", "source_type", "is_enabled"],
    )

    # 7. Create website_url_rules for configurable content classification & exclusions.
    op.create_table(
        "website_url_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("target_content_type", sa.String(length=32), nullable=False),
        sa.Column("match_mode", sa.String(length=24), nullable=False, server_default="glob"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("notes", sa.String(length=255), nullable=True),
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
            name="fk_wur_website_id_websites",
            ondelete="CASCADE",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_website_url_rules_site_prio",
        "website_url_rules",
        ["website_id", "is_enabled", "priority"],
    )

    # 8. Safely rename & extend source_articles -> website_contents and revisions -> content_revisions.
    op.drop_constraint(
        "fk_source_article_revisions_article_id",
        "source_article_revisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_source_article_revisions_article_rev",
        "source_article_revisions",
        type_="unique",
    )
    op.drop_index("ix_source_article_revisions_article_id", table_name="source_article_revisions")

    op.drop_constraint(
        "fk_source_articles_website_id_websites", "source_articles", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_source_articles_featured_media_id_media_assets",
        "source_articles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_source_articles_near_duplicate_of_id",
        "source_articles",
        type_="foreignkey",
    )
    op.drop_constraint("uq_source_articles_website_url_hash", "source_articles", type_="unique")
    op.drop_index("ft_source_articles_search", table_name="source_articles")
    op.drop_index("ix_source_articles_website_id", table_name="source_articles")
    op.drop_index("ix_source_articles_content_hash", table_name="source_articles")
    op.drop_index("ix_source_articles_published_at", table_name="source_articles")
    op.drop_index("ix_source_articles_status", table_name="source_articles")

    op.rename_table("source_articles", "website_contents")
    op.rename_table("source_article_revisions", "content_revisions")

    op.alter_column(
        "content_revisions",
        "article_id",
        new_column_name="content_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.add_column(
        "content_revisions",
        sa.Column("content_type", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_content_revisions_content_id",
        "content_revisions",
        "website_contents",
        ["content_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_content_revisions_content_rev",
        "content_revisions",
        ["content_id", "revision_number"],
    )
    op.create_index("ix_content_revisions_content_id", "content_revisions", ["content_id"])

    op.alter_column(
        "website_contents",
        "discovered_at",
        new_column_name="first_discovered_at",
        existing_type=sa.DateTime(),
        nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.add_column(
        "website_contents",
        sa.Column("content_type", sa.String(length=32), nullable=False, server_default="page"),
    )
    op.add_column(
        "website_contents",
        sa.Column(
            "classification_method",
            sa.String(length=32),
            nullable=False,
            server_default="default_rule",
        ),
    )
    op.add_column(
        "website_contents",
        sa.Column(
            "manual_classification_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "website_contents",
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "website_contents",
        sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
    )
    op.add_column(
        "website_contents",
        sa.Column("h1_text", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "website_contents",
        sa.Column(
            "extracted_content",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
        ),
    )
    op.add_column(
        "website_contents",
        sa.Column("structured_data_json", sa.JSON(), nullable=True),
    )
    op.add_column("website_contents", sa.Column("http_status", sa.Integer(), nullable=True))
    op.add_column(
        "website_contents",
        sa.Column(
            "extraction_status",
            sa.String(length=32),
            nullable=False,
            server_default="extracted",
        ),
    )
    op.add_column(
        "website_contents",
        sa.Column("extraction_error", sa.String(length=500), nullable=True),
    )
    op.add_column("website_contents", sa.Column("discovery_sources", sa.JSON(), nullable=True))
    op.add_column(
        "website_contents",
        sa.Column(
            "last_discovered_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_foreign_key(
        "fk_website_contents_website_id_websites",
        "website_contents",
        "websites",
        ["website_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_website_contents_featured_media_id_media_assets",
        "website_contents",
        "media_assets",
        ["featured_media_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_website_contents_near_duplicate_of_id",
        "website_contents",
        "website_contents",
        ["near_duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_website_contents_website_url_hash",
        "website_contents",
        ["website_id", "url_hash"],
    )
    op.create_index(
        "ix_website_contents_website_type",
        "website_contents",
        ["website_id", "content_type"],
    )
    op.create_index(
        "ix_website_contents_extraction_status",
        "website_contents",
        ["website_id", "extraction_status"],
    )
    op.create_index("ix_website_contents_content_hash", "website_contents", ["content_hash"])
    op.create_index("ix_website_contents_published_at", "website_contents", ["published_at"])
    op.create_index("ix_website_contents_status", "website_contents", ["status"])
    op.create_index(
        "ft_website_contents_search",
        "website_contents",
        ["title", "meta_description", "markdown_content"],
        mysql_prefix="FULLTEXT",
    )

    # Backfill existing website_contents rows and reclassify URLs accurately without AI.
    conn.execute(
        sa.text(
            "UPDATE website_contents "
            "SET url = canonical_url, "
            "    extracted_content = markdown_content, "
            "    last_discovered_at = first_discovered_at, "
            "    http_status = 200, "
            "    extraction_status = CASE "
            "        WHEN status IN ('failed', 'error') THEN 'failed' "
            "        WHEN status = 'discovered' THEN 'pending' "
            "        ELSE 'extracted' "
            "    END, "
            "    discovery_sources = JSON_ARRAY('legacy_scan')"
        )
    )

    site_domains = {
        r[0]: r[1] for r in conn.execute(sa.text("SELECT id, domain FROM websites")).fetchall()
    }
    content_rows = conn.execute(
        sa.text("SELECT id, website_id, canonical_url FROM website_contents")
    ).fetchall()
    for cid, wid, canon_url in content_rows:
        domain = site_domains.get(wid, "")
        decision = classify_url(canon_url, domain=domain)
        conn.execute(
            sa.text(
                "UPDATE website_contents "
                "SET content_type = :ctype, classification_method = :cmethod "
                "WHERE id = :cid"
            ),
            {"ctype": decision.content_type, "cmethod": decision.classification_method, "cid": cid},
        )

    # 9. Extend website_scan_logs and create website_scan_items.
    op.add_column(
        "website_scan_logs",
        sa.Column("scan_mode", sa.String(length=32), nullable=False, server_default="full"),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column(
            "urls_pending_extraction",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("excluded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("homepage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("page_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("blog_post_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("other_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("current_source", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("current_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("discovered_sitemaps_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("sources_completed_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "website_scan_logs",
        sa.Column("sources_failed_json", sa.JSON(), nullable=True),
    )

    op.create_table(
        "website_scan_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scan_log_id", sa.BigInteger(), nullable=False),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("normalized_url", sa.String(length=1000), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False, server_default="page"),
        sa.Column("discovery_sources", sa.JSON(), nullable=True),
        sa.Column("discovered_title", sa.String(length=500), nullable=True),
        sa.Column("discovered_published_at", sa.DateTime(), nullable=True),
        sa.Column("discovered_modified_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(length=120), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
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
            ["scan_log_id"],
            ["website_scan_logs.id"],
            name="fk_wsi_scan_log_id_scan_logs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_wsi_website_id_websites",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["website_contents.id"],
            name="fk_wsi_content_id_contents",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("scan_log_id", "url_hash", name="uq_website_scan_items_scan_url"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_website_scan_items_scan_status",
        "website_scan_items",
        ["scan_log_id", "status"],
    )
    op.create_index(
        "ix_website_scan_items_site_status",
        "website_scan_items",
        ["website_id", "status"],
    )


def _slugify(raw: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return (cleaned or fallback)[:150]


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_table("website_scan_items")

    for col in (
        "sources_failed_json",
        "sources_completed_json",
        "discovered_sitemaps_json",
        "current_url",
        "current_source",
        "other_count",
        "blog_post_count",
        "page_count",
        "homepage_count",
        "excluded_count",
        "urls_pending_extraction",
        "scan_mode",
    ):
        op.drop_column("website_scan_logs", col)

    # Restore source_articles & source_article_revisions safely.
    op.drop_constraint("fk_content_revisions_content_id", "content_revisions", type_="foreignkey")
    op.drop_constraint("uq_content_revisions_content_rev", "content_revisions", type_="unique")
    op.drop_index("ix_content_revisions_content_id", table_name="content_revisions")

    op.drop_constraint(
        "fk_website_contents_website_id_websites", "website_contents", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_website_contents_featured_media_id_media_assets",
        "website_contents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_website_contents_near_duplicate_of_id", "website_contents", type_="foreignkey"
    )
    op.drop_constraint("uq_website_contents_website_url_hash", "website_contents", type_="unique")
    op.drop_index("ft_website_contents_search", table_name="website_contents")
    op.drop_index("ix_website_contents_website_type", table_name="website_contents")
    op.drop_index("ix_website_contents_extraction_status", table_name="website_contents")
    op.drop_index("ix_website_contents_content_hash", table_name="website_contents")
    op.drop_index("ix_website_contents_published_at", table_name="website_contents")
    op.drop_index("ix_website_contents_status", table_name="website_contents")

    op.rename_table("content_revisions", "source_article_revisions")
    op.rename_table("website_contents", "source_articles")

    op.drop_column("source_article_revisions", "content_type")
    op.alter_column(
        "source_article_revisions",
        "content_id",
        new_column_name="article_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

    for col in (
        "last_discovered_at",
        "discovery_sources",
        "extraction_error",
        "extraction_status",
        "http_status",
        "structured_data_json",
        "extracted_content",
        "h1_text",
        "url",
        "is_excluded",
        "manual_classification_override",
        "classification_method",
        "content_type",
    ):
        op.drop_column("source_articles", col)

    op.alter_column(
        "source_articles",
        "first_discovered_at",
        new_column_name="discovered_at",
        existing_type=sa.DateTime(),
        nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    op.create_foreign_key(
        "fk_source_articles_website_id_websites",
        "source_articles",
        "websites",
        ["website_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_source_articles_featured_media_id_media_assets",
        "source_articles",
        "media_assets",
        ["featured_media_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_source_articles_near_duplicate_of_id",
        "source_articles",
        "source_articles",
        ["near_duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_source_articles_website_url_hash",
        "source_articles",
        ["website_id", "url_hash"],
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

    op.create_foreign_key(
        "fk_source_article_revisions_article_id",
        "source_article_revisions",
        "source_articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_source_article_revisions_article_rev",
        "source_article_revisions",
        ["article_id", "revision_number"],
    )
    op.create_index(
        "ix_source_article_revisions_article_id",
        "source_article_revisions",
        ["article_id"],
    )

    op.drop_table("website_url_rules")
    op.drop_table("website_discovery_sources")

    # Recreate brands from website merged fields cleanly.
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

    op.add_column("websites", sa.Column("brand_id", sa.BigInteger(), nullable=True))
    op.add_column("media_assets", sa.Column("brand_id", sa.BigInteger(), nullable=True))

    rows = conn.execute(
        sa.text(
            "SELECT id, name, brand_name, brand_slug, logo_url, brand_description, "
            "target_audience, target_country, primary_language, secondary_languages, "
            "tone, target_keywords, restricted_keywords, default_hashtags, default_cta, "
            "writing_guidelines, ai_instructions "
            "FROM websites"
        )
    ).fetchall()
    used_slugs: set[str] = set()
    for row in rows:
        m = row._mapping
        bname = m["brand_name"] or m["name"]
        base_slug = m["brand_slug"] or _slugify(bname, f"brand-{m['id']}")
        slug = base_slug
        if slug in used_slugs:
            slug = f"{base_slug[:140]}-{m['id']}"
        used_slugs.add(slug)
        res = conn.execute(
            sa.text(
                "INSERT INTO brands (name, slug, logo_url, description, target_audience, "
                "target_country, primary_language, secondary_languages, tone, target_keywords, "
                "restricted_keywords, default_hashtags, default_cta, writing_guidelines, "
                "ai_instructions, is_active) "
                "VALUES (:name, :slug, :logo_url, :description, :target_audience, "
                ":target_country, :primary_language, :secondary_languages, :tone, "
                ":target_keywords, :restricted_keywords, :default_hashtags, :default_cta, "
                ":writing_guidelines, :ai_instructions, 1)"
            ),
            {
                "name": bname,
                "slug": slug,
                "logo_url": m["logo_url"],
                "description": m["brand_description"],
                "target_audience": m["target_audience"],
                "target_country": m["target_country"],
                "primary_language": m["primary_language"] or "en",
                "secondary_languages": json.dumps(m["secondary_languages"])
                if isinstance(m["secondary_languages"], list)
                else m["secondary_languages"],
                "tone": m["tone"],
                "target_keywords": json.dumps(m["target_keywords"])
                if isinstance(m["target_keywords"], list)
                else m["target_keywords"],
                "restricted_keywords": json.dumps(m["restricted_keywords"])
                if isinstance(m["restricted_keywords"], list)
                else m["restricted_keywords"],
                "default_hashtags": json.dumps(m["default_hashtags"])
                if isinstance(m["default_hashtags"], list)
                else m["default_hashtags"],
                "default_cta": m["default_cta"],
                "writing_guidelines": m["writing_guidelines"],
                "ai_instructions": m["ai_instructions"],
            },
        )
        brand_id = res.lastrowid
        conn.execute(
            sa.text("UPDATE websites SET brand_id = :bid WHERE id = :wid"),
            {"bid": brand_id, "wid": m["id"]},
        )
        conn.execute(
            sa.text("UPDATE media_assets SET brand_id = :bid WHERE website_id = :wid"),
            {"bid": brand_id, "wid": m["id"]},
        )

    op.drop_constraint("fk_media_assets_website_id_websites", "media_assets", type_="foreignkey")
    op.drop_index("ix_media_assets_website_id", table_name="media_assets")
    op.drop_column("media_assets", "website_id")
    op.create_index("ix_media_assets_brand_id", "media_assets", ["brand_id"])
    op.create_foreign_key(
        "fk_media_assets_brand_id_brands",
        "media_assets",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column("websites", "brand_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_constraint("uq_websites_domain", "websites", type_="unique")
    op.drop_constraint("fk_websites_category_id_categories", "websites", type_="foreignkey")
    op.drop_index("ix_websites_category_id", table_name="websites")
    op.create_index("ix_websites_brand_id", "websites", ["brand_id"])
    op.create_unique_constraint("uq_websites_brand_domain", "websites", ["brand_id", "domain"])
    op.create_foreign_key(
        "fk_websites_brand_id_brands",
        "websites",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    for col in (
        "crawl_max_urls_per_run",
        "crawl_batch_size",
        "single_source_only",
        "ai_instructions",
        "writing_guidelines",
        "default_cta",
        "default_hashtags",
        "restricted_keywords",
        "target_keywords",
        "tone",
        "secondary_languages",
        "primary_language",
        "target_country",
        "target_audience",
        "brand_description",
        "logo_url",
        "brand_slug",
        "brand_name",
        "category_id",
    ):
        op.drop_column("websites", col)

    op.drop_table("website_categories")
