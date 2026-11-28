from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_ROOT
from app.core.security import encrypt_secret
from app.repositories.ai_repo import SQLAlchemyAiRepository
from app.repositories.category_repo import SQLAlchemyWebsiteCategoryRepository
from app.repositories.content_repo import SQLAlchemyContentRepository
from app.repositories.keyword_approval_repo import SQLAlchemyKeywordApprovalRepository
from app.repositories.social_post_repo import SQLAlchemySocialPostRepository
from app.repositories.social_profile_repo import SQLAlchemySocialProfileRepository
from app.repositories.website_repo import SQLAlchemyWebsiteRepository


def _resolve_isolated_test_mysql_url() -> str | None:
    env_val = os.getenv("CONTENTHUB_TEST_DATABASE_URL", "").strip()
    if env_val:
        return env_val
    for dotenv_path in (Path(BACKEND_ROOT).parent / ".env", Path(BACKEND_ROOT) / ".env"):
        if not dotenv_path.is_file():
            continue
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == "CONTENTHUB_TEST_DATABASE_URL":
                return val.strip().strip('"').strip("'")
    return None


@pytest.mark.mysql
def test_live_mysql_phase3_migrations_seed_and_repositories() -> None:
    test_db_url = _resolve_isolated_test_mysql_url()
    if not test_db_url:
        pytest.skip("CONTENTHUB_TEST_DATABASE_URL is not configured.")

    parsed = make_url(test_db_url)
    db_name = (parsed.database or "").lower()
    if not db_name or "_test" not in db_name:
        pytest.fail(
            f"Refusing to run destructive schema tests on non-test DB '{parsed.database}'."
        )

    engine = create_engine(test_db_url, pool_pre_ping=True, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            existing_tables = list(
                conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": parsed.database},
                )
                .scalars()
                .all()
            )
            for tbl in existing_tables:
                conn.execute(text(f"DROP TABLE IF EXISTS `{tbl}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        alembic_cfg = AlembicConfig(str(Path(BACKEND_ROOT) / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(Path(BACKEND_ROOT) / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)

        # 1. Upgrade through Phase 2.1, insert representative data, then upgrade to Phase 3 head.
        alembic_command.upgrade(alembic_cfg, "20261127_0003")

        with engine.begin() as conn:
            cat_id = int(
                conn.execute(
                    text("SELECT id FROM website_categories WHERE slug = 'casino' LIMIT 1")
                ).scalar_one()
            )
            res_site = conn.execute(
                text(
                    "INSERT INTO websites (category_id, name, brand_name, domain, website_type, "
                    "discovery_method, primary_language, status) "
                    "VALUES (:cid, 'MySQL P3 Site', 'MySQL P3', 'p3-mysql.example.com', "
                    "'wordpress', 'auto', 'Taglish', 'active')"
                ),
                {"cid": cat_id},
            )
            site_id = int(res_site.lastrowid)

        alembic_command.upgrade(alembic_cfg, "20261127_0004")

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO website_contents "
                    "(website_id, content_type, classification_method, title, url, canonical_url, "
                    "url_hash, content_hash, keywords, word_count, extraction_status, status) "
                    "VALUES "
                    "(:wid, 'blog_post', 'path', 'Fixed Odds vs Dynamic Odds: Guide', "
                    "'https://p3-mysql.example.com/blog/fixed-odds-vs-dynamic-odds', "
                    "'https://p3-mysql.example.com/blog/fixed-odds-vs-dynamic-odds', "
                    ":uh1, :ch1, '[\"Fixed Odds vs Dynamic Odds\", \"Fixed odds\"]', "
                    "320, 'extracted', 'extracted'), "
                    "(:wid, 'page', 'path', 'Pending Discovery Page', "
                    "'https://p3-mysql.example.com/promotions', "
                    "'https://p3-mysql.example.com/promotions', "
                    ":uh2, :ch2, '[]', 0, 'pending', 'discovered')"
                ),
                {
                    "wid": site_id,
                    "uh1": "1" * 64,
                    "ch1": "2" * 64,
                    "uh2": "3" * 64,
                    "ch2": "4" * 64,
                },
            )

        alembic_command.upgrade(alembic_cfg, "head")

        with engine.connect() as conn:
            table_rows = conn.execute(
                text(
                    "SELECT table_name, engine, table_collation "
                    "FROM information_schema.tables WHERE table_schema = :schema"
                ),
                {"schema": parsed.database},
            ).all()
            table_meta = {row[0]: (row[1], row[2]) for row in table_rows}

            auto_gen_col = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'websites' "
                    "AND column_name IN "
                    "('auto_generate_require_published_at', 'auto_generate_context_mode')"
                ),
                {"schema": parsed.database},
            ).scalars().all()
            assert set(auto_gen_col) == {
                "auto_generate_require_published_at",
                "auto_generate_context_mode",
            }

            platform_count = int(
                conn.execute(text("SELECT COUNT(*) FROM platforms")).scalar_one()
            )
            prompt_count = int(
                conn.execute(text("SELECT COUNT(*) FROM prompt_templates")).scalar_one()
            )
            assert platform_count >= 8
            assert prompt_count >= 9

            preserved_site_name = conn.execute(
                text("SELECT name FROM websites WHERE id = :id"),
                {"id": site_id},
            ).scalar_one()
            assert preserved_site_name == "MySQL P3 Site"

        phase3_tables = {
            "platforms",
            "social_profiles",
            "ai_providers",
            "website_knowledge_profiles",
            "website_knowledge_profile_revisions",
            "prompt_templates",
            "prompt_template_revisions",
            "ai_response_cache",
            "ai_generation_jobs",
            "ai_generation_logs",
            "social_posts",
            "social_post_revisions",
            "content_keywords",
            "content_keyword_revisions",
            "content_approvals",
            "content_approval_history",
        }
        assert phase3_tables.issubset(table_meta.keys())
        for tbl in phase3_tables:
            assert table_meta[tbl][0] == "InnoDB"
            assert str(table_meta[tbl][1]).startswith("utf8mb4")

        with engine.connect() as conn:
            backfill_statuses = set(
                conn.execute(
                    text("SELECT status FROM content_approvals WHERE website_id = :wid"),
                    {"wid": site_id},
                )
                .scalars()
                .all()
            )
            assert backfill_statuses == {"pending_review", "awaiting_extraction"}
            ai_job_count = int(
                conn.execute(text("SELECT COUNT(*) FROM ai_generation_jobs")).scalar_one()
            )
            assert ai_job_count == 0

        # 2. Verify clean incremental downgrade 0005 -> 0004, then full 0003, then re-upgrade head.
        alembic_command.downgrade(alembic_cfg, "20261127_0004")
        alembic_command.upgrade(alembic_cfg, "head")
        alembic_command.downgrade(alembic_cfg, "20261127_0003")
        alembic_command.upgrade(alembic_cfg, "head")

        # 3. Exercise real SQLAlchemy Phase 3 repositories & locking on MySQL 8.0.
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = SessionLocal()
        try:
            category_repo = SQLAlchemyWebsiteCategoryRepository(db)
            website_repo = SQLAlchemyWebsiteRepository(db)
            content_repo = SQLAlchemyContentRepository(db)
            profile_repo = SQLAlchemySocialProfileRepository(db)
            ai_repo = SQLAlchemyAiRepository(db)
            post_repo = SQLAlchemySocialPostRepository(db)

            cats = category_repo.list_all()
            assert len(cats) >= 8
            site = website_repo.get_by_id(site_id)
            assert site is not None

            fb = profile_repo.get_platform_by_key("facebook")
            x_plat = profile_repo.get_platform_by_key("twitter")
            assert fb is not None and x_plat is not None
            assert x_plat.url_counts_as_chars == 23

            enc_key = Fernet.generate_key().decode("ascii")
            enc_secret = encrypt_secret("fb-secret-token-live", enc_key)

            prof1 = profile_repo.create(
                {
                    "website_id": site.id,
                    "platform_id": fb.id,
                    "profile_name": "Bygame Official FB",
                    "is_active": True,
                    "publishing_method": "api",
                    "credential_status": "configured",
                    "generation_enabled": True,
                    "automatic_generation_enabled": True,
                    "auto_publish_enabled": False,
                    "encrypted_access_token": enc_secret,
                }
            )
            prof2 = profile_repo.create(
                {
                    "website_id": site.id,
                    "platform_id": fb.id,
                    "profile_name": "Bygame Promo FB",
                    "is_active": True,
                    "publishing_method": "manual",
                    "credential_status": "not_configured",
                    "generation_enabled": True,
                    "automatic_generation_enabled": False,
                    "auto_publish_enabled": False,
                }
            )
            assert prof1.id != prof2.id
            assert len(profile_repo.list_for_website(site.id)) == 2
            assert prof1.encrypted_access_token != "fb-secret-token-live"

            provider = ai_repo.create_provider(
                {
                    "name": "Gemini Free-First Live",
                    "provider_type": "gemini",
                    "encrypted_api_key": encrypt_secret("AIzaLiveFakeSecret99887766", enc_key),
                    "selected_model": "gemini-3.5-flash-lite",
                    "default_temperature": 0.4,
                    "max_output_tokens": 1500,
                    "request_timeout_seconds": 45,
                    "max_retry_attempts": 2,
                    "daily_request_limit": 100,
                    "daily_token_limit": 250000,
                    "per_minute_request_limit": 10,
                    "generation_enabled": True,
                    "response_caching_enabled": True,
                    "token_optimization_enabled": True,
                    "allow_paid_fallback": False,
                    "is_default": True,
                    "is_active": True,
                    "last_test_status": "untested",
                }
            )
            assert provider.id > 0

            job = ai_repo.create_job(
                {
                    "job_uuid": "mysql-live-job-001",
                    "job_type": "social_generation",
                    "trigger_type": "manual",
                    "website_id": site.id,
                    "website_content_id": None,
                    "target_profile_ids_json": [prof1.id, prof2.id],
                    "ai_provider_id": provider.id,
                    "context_mode": "optimized",
                    "force_regenerate": False,
                    "idempotency_key": "mysql-live-idem-001",
                    "status": "queued",
                    "attempt_count": 0,
                    "max_attempts": 2,
                }
            )
            claimed = ai_repo.claim_job(job.id, worker_id="mysql-worker-1")
            assert claimed is not None and claimed.status == "processing"
            # Second claim on processing job must fail atomically.
            assert ai_repo.claim_job(job.id, worker_id="mysql-worker-2") is None

            content = content_repo.create(
                {
                    "website_id": site.id,
                    "content_type": "blog_post",
                    "classification_method": "path",
                    "title": "Live MySQL Blog Article",
                    "url": "https://p3-mysql.example.com/blog/live-p3",
                    "canonical_url": "https://p3-mysql.example.com/blog/live-p3",
                    "url_hash": "a" * 64,
                    "markdown_content": "# Live Post\n\nBody text.",
                    "optimized_context": "Title: Live MySQL Blog Article",
                    "keywords": ["mysql"],
                    "discovery_sources": ["sitemap"],
                    "content_hash": "b" * 64,
                    "word_count": 4,
                    "extraction_status": "extracted",
                    "status": "extracted",
                }
            )

            post = post_repo.create_post(
                {
                    "website_id": site.id,
                    "website_content_id": content.id,
                    "social_profile_id": prof1.id,
                    "platform_id": fb.id,
                    "ai_generation_job_id": job.id,
                    "ai_provider_id": provider.id,
                    "generation_model": "gemini-3.5-flash-lite",
                    "caption": "Initial MySQL draft caption.",
                    "assembled_content": "Initial MySQL draft caption.",
                    "hashtags_json": ["#MySQL"],
                    "source_url": content.canonical_url,
                    "language": "Taglish",
                    "character_count": 28,
                    "character_limit": fb.default_max_chars,
                    "status": "pending_review",
                    "is_manually_edited": False,
                    "dedupe_key": "c" * 64,
                },
                change_type="initial_generated",
            )
            assert post.current_version == 1

            updated_post = post_repo.update_post(
                post.id,
                {
                    "caption": "Edited MySQL draft caption.",
                    "assembled_content": "Edited MySQL draft caption.",
                    "is_manually_edited": True,
                },
                create_revision=True,
                change_type="manual_edit",
                notes="Admin edit",
            )
            assert updated_post is not None and updated_post.current_version == 2
            revisions = post_repo.list_revisions(post.id)
            assert [r.version_number for r in revisions] == [2, 1]

            kw_app_repo = SQLAlchemyKeywordApprovalRepository(db)
            kw_row = kw_app_repo.upsert_keyword(
                website_id=site.id,
                website_content_id=content.id,
                data={
                    "focus_keyphrase": "Live MySQL SEO Phrase",
                    "secondary_keywords_json": ["mysql secondary one", "mysql secondary two"],
                    "anchor_text_variations_json": ["Live MySQL SEO Phrase"],
                    "image_alt_suggestions_json": [
                        {
                            "image_url": "https://p3-mysql.example.com/img/live.webp",
                            "current_alt": None,
                            "suggested_alt": "Diagram showing live MySQL SEO schema workflow",
                            "context": "Featured article image",
                        }
                    ],
                    "approval_status": "approved",
                    "suggestion_source": "manual",
                    "is_admin_locked": True,
                },
                change_note="Approved in MySQL live test",
            )
            assert kw_row.focus_keyphrase_norm == "live mysql seo phrase"
            app_row, prev_st = kw_app_repo.upsert_approval(
                website_id=site.id,
                website_content_id=content.id,
                data={
                    "status": "approved",
                    "classified_content_type": "blog_post",
                    "submitted_content_hash": content.content_hash,
                },
            )
            assert prev_st is None
            kw_app_repo.record_approval_history(
                content_approval_id=app_row.id,
                from_status=None,
                to_status="approved",
                content_type="blog_post",
                focus_keyphrase=kw_row.focus_keyphrase,
                action="approved",
                note="MySQL integration check",
                acted_by=None,
            )
            counts = kw_app_repo.get_status_counts(website_id=site.id)
            assert counts["approved"] >= 1
            map_rows, map_total = kw_app_repo.list_approved_keyword_entries(
                page=1, page_size=10, website_id=site.id, approved_only=True
            )
            assert map_total >= 1 and map_rows[0][1].focus_keyphrase == "Live MySQL SEO Phrase"
            assert len(kw_app_repo.list_keyword_revisions(kw_row.id)) >= 1
            assert len(kw_app_repo.list_approval_history(app_row.id)) == 1
        finally:
            db.close()
    finally:
        engine.dispose()
