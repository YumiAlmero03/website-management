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
from app.repositories.article_repo import SQLAlchemyArticleRepository
from app.repositories.brand_repo import SQLAlchemyBrandRepository
from app.repositories.media_repo import SQLAlchemyMediaRepository
from app.repositories.scan_log_repo import SQLAlchemyScanLogRepository
from app.repositories.website_repo import SQLAlchemyWebsiteRepository


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
def test_live_mysql_alembic_migrations_and_phase2_repositories() -> None:
    """Verify full Alembic upgrade/downgrade/upgrade and SQLAlchemy Phase 2 CRUD on live MySQL."""
    cfg, test_url = _get_isolated_test_url()
    engine = create_mysql_engine(settings=cfg, url_override=test_url)

    try:
        # Reset only the dedicated *_test schema so migrations run from clean base.
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            tables = [row[0] for row in conn.execute(text("SHOW TABLES")).fetchall()]
            for table_name in tables:
                conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        alembic_cfg = AlembicConfig(str(Path(BACKEND_ROOT) / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(Path(BACKEND_ROOT) / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", test_url)

        # Upgrade through Phase 1 + Phase 2, test downgrade to Phase 1, then re-upgrade.
        alembic_command.upgrade(alembic_cfg, "head")
        alembic_command.downgrade(alembic_cfg, "20261126_0001")
        alembic_command.upgrade(alembic_cfg, "head")

        # Verify expected Phase 1 + Phase 2 tables exist with InnoDB & utf8mb4.
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
                )
            ).fetchall()
            table_meta = {r[0]: (r[1], r[2]) for r in rows}

        expected_tables = {
            "users",
            "sessions",
            "application_settings",
            "activity_logs",
            "brands",
            "media_assets",
            "websites",
            "source_articles",
            "source_article_revisions",
            "website_scan_logs",
        }
        assert expected_tables.issubset(table_meta.keys())
        for tbl in expected_tables:
            assert table_meta[tbl][0] == "InnoDB"
            assert str(table_meta[tbl][1]).startswith("utf8mb4")

        # Exercise real SQLAlchemy repositories against MySQL 8.0.
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = SessionLocal()
        try:
            brand_repo = SQLAlchemyBrandRepository(db)
            website_repo = SQLAlchemyWebsiteRepository(db)
            article_repo = SQLAlchemyArticleRepository(db)
            scan_repo = SQLAlchemyScanLogRepository(db)
            media_repo = SQLAlchemyMediaRepository(db)

            brand = brand_repo.create(
                {
                    "name": "Live MySQL Brand",
                    "slug": "live-mysql-brand",
                    "primary_language": "en",
                    "secondary_languages": ["fil", "taglish"],
                }
            )
            site = website_repo.create(
                {
                    "brand_id": brand.id,
                    "name": "Live MySQL Site",
                    "domain": "mysql-test.example.com",
                    "website_type": "wordpress",
                    "discovery_method": "rss",
                }
            )
            scan = scan_repo.create(
                website_id=site.id, scan_method="rss", trigger_type="manual"
            )
            claimed = scan_repo.claim_pending(scan.id)
            assert claimed is not None and claimed.status == "processing"
            # Second claim returns None (transactional lock respected).
            assert scan_repo.claim_pending(scan.id) is None

            media = media_repo.create(
                brand_id=brand.id,
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
            article = article_repo.create(
                {
                    "website_id": site.id,
                    "featured_media_id": media.id,
                    "title": "MySQL Integration Article",
                    "canonical_url": "https://mysql-test.example.com/blog/post-1",
                    "url_hash": "d" * 64,
                    "markdown_content": "# Heading\n\nBody text.",
                    "optimized_context": "Title: MySQL Integration Article",
                    "keywords": ["mysql", "contenthub"],
                    "content_hash": "e" * 64,
                    "word_count": 3,
                    "status": "optimized",
                }
            )
            rev = article_repo.create_revision(
                article_id=article.id,
                revision_number=1,
                title=article.title,
                meta_description=None,
                markdown_content=article.markdown_content,
                content_hash=article.content_hash,
            )
            assert rev.revision_number == 1
            assert article_repo.count_by_website(site.id) == 1
        finally:
            db.close()
    finally:
        engine.dispose()
