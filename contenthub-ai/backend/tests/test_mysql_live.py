from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_ROOT, Settings
from app.database import check_database_connection, create_mysql_engine
from app.repositories.category_repo import SQLAlchemyWebsiteCategoryRepository
from app.repositories.content_repo import SQLAlchemyContentRepository
from app.repositories.media_repo import SQLAlchemyMediaRepository
from app.repositories.scan_log_repo import SQLAlchemyScanLogRepository
from app.repositories.website_repo import SQLAlchemyWebsiteRepository
from app.repositories.website_source_repo import SQLAlchemyWebsiteSourceConfigRepository


def _get_isolated_test_url() -> tuple[Settings, str]:
    cfg = Settings()
    test_url = (
        os.environ.get("CONTENTHUB_TEST_DATABASE_URL", "").strip()
        or cfg.contenthub_test_database_url.strip()
    )
    if not test_url:
        pytest.skip(
            "CONTENTHUB_TEST_DATABASE_URL is not set; skipping live MySQL integration test."
        )
    db_name = urlparse(test_url).path.lstrip("/")
    if not db_name.endswith("_test"):
        pytest.fail(
            f"Refusing to run destructive test migrations against non-test database '{db_name}'."
        )
    return cfg, test_url


@pytest.mark.mysql
def test_live_mysql_connectivity_and_innodb_utf8mb4() -> None:
    cfg, test_url = _get_isolated_test_url()
    engine = create_mysql_engine(settings=cfg, url_override=test_url)
    try:
        diag = check_database_connection(settings=cfg, engine=engine)
    finally:
        engine.dispose()

    assert diag.connected is True, diag.error
    assert diag.server_version is not None
    assert diag.innodb_available is True
    assert diag.character_set is not None and diag.character_set.lower().startswith("utf8mb4")


@pytest.mark.mysql
def test_live_mysql_phase2_1_migration_data_preservation_and_repositories() -> None:
    """Verify full Alembic upgrade, Phase 2->2.1 data preservation, downgrade, and MySQL CRUD."""
    cfg, test_url = _get_isolated_test_url()
    engine = create_mysql_engine(settings=cfg, url_override=test_url)

    try:
        # Reset only the dedicated *_test schema so migrations run cleanly.
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            tables = [row[0] for row in conn.execute(text("SHOW TABLES")).fetchall()]
            for table_name in tables:
                conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        alembic_cfg = AlembicConfig(str(Path(BACKEND_ROOT) / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(Path(BACKEND_ROOT) / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", test_url)

        # 1. Start at Phase 2 (20261126_0002), seed Phase 2 data,
        #    then upgrade to Phase 2.1 (20261127_0003) and verify zero data loss.
        alembic_command.upgrade(alembic_cfg, "20261126_0002")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO brands (name, slug, primary_language, tone, is_active, "
                    "created_at, updated_at) "
                    "VALUES ('Bygame', 'bygame', 'Taglish', 'Energetic', 1, NOW(), NOW())"
                )
            )
            brand_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO websites (brand_id, name, domain, website_type, "
                    "discovery_method, excluded_url_patterns, scan_interval_minutes, "
                    "auto_scan, auto_generate, initial_scan_completed, baseline_mode, "
                    "status, created_at, updated_at) "
                    "VALUES (:bid, 'Bygame Casino', 'bygame.ph', 'nuxt', 'auto', "
                    ":excl, 1440, 1, 0, 1, 'import_existing', 'active', NOW(), NOW())"
                ),
                {"bid": brand_id, "excl": '["/tag/*", "/category/*", "/author/*"]'},
            )
            site_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO media_assets (brand_id, file_name, source_url, created_at) "
                    "VALUES (:bid, 'logo.png', 'https://bygame.ph/logo.png', NOW())"
                ),
                {"bid": brand_id},
            )
            media_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO source_articles (website_id, featured_media_id, title, "
                    "canonical_url, url_hash, content_hash, word_count, status, "
                    "is_historical_baseline, discovered_at, last_checked_at, "
                    "created_at, updated_at) "
                    "VALUES (:wid, :mid, 'Bygame Homepage', 'https://bygame.ph/', "
                    ":uhash, :chash, 120, 'extracted', 0, NOW(), NOW(), NOW(), NOW())"
                ),
                {"wid": site_id, "mid": media_id, "uhash": "a" * 64, "chash": "b" * 64},
            )
            art_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO source_article_revisions (article_id, revision_number, "
                    "title, content_hash, created_at) "
                    "VALUES (:aid, 1, 'Bygame Homepage v1', :chash, NOW())"
                ),
                {"aid": art_id, "chash": "b" * 64},
            )

        alembic_command.upgrade(alembic_cfg, "head")

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
                )
            ).fetchall()
            table_meta = {r[0]: (r[1], r[2]) for r in rows}

            migrated_site = conn.execute(
                text("SELECT brand_name, excluded_url_patterns FROM websites WHERE id = :id"),
                {"id": site_id},
            ).fetchone()
            assert migrated_site is not None
            assert migrated_site[0] == "Bygame"
            assert "/category/*" not in str(migrated_site[1])

            migrated_content = conn.execute(
                text("SELECT content_type, extraction_status FROM website_contents WHERE id = :id"),
                {"id": art_id},
            ).fetchone()
            assert migrated_content == ("homepage", "extracted")

            migrated_media_site = conn.execute(
                text("SELECT website_id FROM media_assets WHERE id = :id"), {"id": media_id}
            ).scalar_one()
            assert migrated_media_site == site_id

        expected_tables = {
            "users",
            "sessions",
            "application_settings",
            "activity_logs",
            "website_categories",
            "websites",
            "website_discovery_sources",
            "website_url_rules",
            "media_assets",
            "website_contents",
            "content_revisions",
            "website_scan_logs",
            "website_scan_items",
        }
        assert expected_tables.issubset(table_meta.keys())
        assert "brands" not in table_meta
        assert "source_articles" not in table_meta
        for tbl in expected_tables:
            assert table_meta[tbl][0] == "InnoDB"
            assert str(table_meta[tbl][1]).startswith("utf8mb4")

        # 2. Test clean downgrade to Phase 2 and re-upgrade back to head.
        alembic_command.downgrade(alembic_cfg, "20261126_0002")
        alembic_command.upgrade(alembic_cfg, "head")

        # 3. Exercise real SQLAlchemy Phase 2.1 repositories against MySQL 8.0.
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = SessionLocal()
        try:
            category_repo = SQLAlchemyWebsiteCategoryRepository(db)
            website_repo = SQLAlchemyWebsiteRepository(db)
            source_repo = SQLAlchemyWebsiteSourceConfigRepository(db)
            content_repo = SQLAlchemyContentRepository(db)
            scan_repo = SQLAlchemyScanLogRepository(db)
            media_repo = SQLAlchemyMediaRepository(db)

            cats = category_repo.list_all()
            assert len(cats) >= 8
            casino_cat = category_repo.get_by_slug("casino")
            assert casino_cat is not None

            site = website_repo.create(
                {
                    "category_id": casino_cat.id,
                    "name": "Live MySQL Site",
                    "brand_name": "Live MySQL Brand",
                    "brand_slug": "live-mysql-brand",
                    "primary_language": "Taglish",
                    "domain": "mysql-test.example.com",
                    "website_type": "nuxt",
                    "discovery_method": "auto",
                }
            )
            src = source_repo.upsert_source(
                website_id=site.id,
                source_type="sitemap",
                endpoint_url="https://mysql-test.example.com/sitemap.xml",
            )
            assert src.is_enabled is True
            rule = source_repo.create_rule(
                {
                    "website_id": site.id,
                    "pattern": "/game/*",
                    "target_content_type": "page",
                    "match_mode": "glob",
                    "priority": 50,
                    "is_enabled": True,
                }
            )
            assert rule.target_content_type == "page"

            scan = scan_repo.create(
                website_id=site.id, scan_method="auto", trigger_type="manual", scan_mode="full"
            )
            claimed = scan_repo.claim_pending(scan.id)
            assert claimed is not None and claimed.status == "processing"
            assert scan_repo.claim_pending(scan.id) is None

            media = media_repo.create(
                website_id=site.id,
                file_name="hero.png",
                file_path=None,
                source_url="https://mysql-test.example.com/hero.png",
                mime_type="image/png",
                file_size=1024,
                width=640,
                height=360,
                alt_text="Hero",
                checksum="c" * 64,
            )
            content = content_repo.create(
                {
                    "website_id": site.id,
                    "featured_media_id": media.id,
                    "content_type": "blog_post",
                    "classification_method": "path",
                    "title": "MySQL Integration Post",
                    "url": "https://mysql-test.example.com/blog/post-1",
                    "canonical_url": "https://mysql-test.example.com/blog/post-1",
                    "url_hash": "d" * 64,
                    "markdown_content": "# Heading\n\nBody text.",
                    "optimized_context": "Title: MySQL Integration Post",
                    "keywords": ["mysql", "contenthub"],
                    "discovery_sources": ["sitemap"],
                    "content_hash": "e" * 64,
                    "word_count": 3,
                    "extraction_status": "extracted",
                    "status": "extracted",
                }
            )
            item = scan_repo.upsert_scan_item(
                scan_log_id=scan.id,
                website_id=site.id,
                url=content.url,
                normalized_url=content.canonical_url,
                url_hash=content.url_hash,
                content_type=content.content_type,
                discovery_sources=["sitemap"],
                status="new",
                content_id=content.id,
            )
            assert item.status == "new"
            rev = content_repo.create_revision(
                content_id=content.id,
                revision_number=1,
                title=content.title,
                meta_description=None,
                markdown_content=content.markdown_content,
                content_hash=content.content_hash,
                content_type=content.content_type,
            )
            assert rev.revision_number == 1
            stats = content_repo.get_stats(website_id=site.id)
            assert stats["blog_post_count"] == 1
        finally:
            db.close()
    finally:
        engine.dispose()
