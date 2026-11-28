from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.base import utc_now_naive
from app.repositories.publishing_repo import SQLAlchemyPublishingRepository
from app.repositories.social_profile_repo import SQLAlchemySocialProfileRepository
from tests.test_phase3_mysql_live import _resolve_isolated_test_mysql_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.mysql
def test_live_mysql_phase4_migration_downgrade_locking_and_history_preservation() -> None:
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

        alembic_cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)

        # 1. Start at Phase 3 head (20261128_0007) and seed existing website/profile/approved draft
        alembic_command.upgrade(alembic_cfg, "20261128_0007")
        with engine.begin() as conn:
            cat_id = int(
                conn.execute(
                    text("SELECT id FROM website_categories WHERE slug = 'casino' LIMIT 1")
                ).scalar_one()
            )
            fb_id = int(
                conn.execute(
                    text("SELECT id FROM platforms WHERE platform_key = 'facebook' LIMIT 1")
                ).scalar_one()
            )
            res_site = conn.execute(
                text(
                    "INSERT INTO websites (category_id, name, brand_name, domain, website_type, "
                    "discovery_method, primary_language, status) "
                    "VALUES (:cid, 'Phase 4 Live', 'Phase4Brand', 'p4-live.example.com', "
                    "'wordpress', 'auto', 'English', 'active')"
                ),
                {"cid": cat_id},
            )
            site_id = int(res_site.lastrowid)

            res_prof = conn.execute(
                text(
                    "INSERT INTO social_profiles "
                    "(website_id, platform_id, profile_name, publishing_method, "
                    "credential_status, is_active, generation_enabled, "
                    "automatic_generation_enabled) "
                    "VALUES (:wid, :pid, 'P4 Legacy Manual Profile', 'manual', "
                    "'configured', 1, 1, 0)"
                ),
                {"wid": site_id, "pid": fb_id},
            )
            profile_id = int(res_prof.lastrowid)

            res_post = conn.execute(
                text(
                    "INSERT INTO social_posts "
                    "(website_id, social_profile_id, platform_id, caption, assembled_content, "
                    "hashtags_json, validation_warnings_json, source_url, language, "
                    "character_count, status, current_version) "
                    "VALUES (:wid, :spid, :pid, 'Existing approved draft', "
                    "'Existing approved draft', '[]', '[]', 'https://p4-live.example.com/p1', "
                    "'English', 23, 'approved', 1)"
                ),
                {"wid": site_id, "spid": profile_id, "pid": fb_id},
            )
            post_id = int(res_post.lastrowid)

        # 2. Upgrade to 20261128_0008 and verify schema, InnoDB/utf8mb4, and backfills
        alembic_command.upgrade(alembic_cfg, "20261128_0008")

        with engine.connect() as conn:
            table_rows = conn.execute(
                text(
                    "SELECT table_name, engine, table_collation "
                    "FROM information_schema.tables WHERE table_schema = :schema"
                ),
                {"schema": parsed.database},
            ).all()
            table_meta = {row[0]: (row[1], row[2]) for row in table_rows}

            phase4_tables = {
                "social_profile_connections",
                "oauth_state_sessions",
                "social_post_media",
                "publishing_schedules",
                "publishing_jobs",
                "publishing_logs",
                "publication_records",
            }
            assert phase4_tables.issubset(table_meta.keys())
            for tbl in phase4_tables:
                assert table_meta[tbl][0] == "InnoDB"
                assert str(table_meta[tbl][1]).startswith("utf8mb4")

            backfilled_elig = conn.execute(
                text("SELECT publishing_eligibility_status FROM social_profiles WHERE id = :id"),
                {"id": profile_id},
            ).scalar_one()
            assert backfilled_elig == "manual_only"

            backfilled_pub_status = conn.execute(
                text("SELECT publishing_status FROM social_posts WHERE id = :id"),
                {"id": post_id},
            ).scalar_one()
            assert backfilled_pub_status == "approved"

        # 3. Verify transactional FOR UPDATE claim, stale verification_required recovery,
        #    and permanent publication_records preservation on profile delete
        SessionLocal = sessionmaker(bind=engine, future=True)
        with SessionLocal() as db:
            pub_repo = SQLAlchemyPublishingRepository(db)
            prof_repo = SQLAlchemySocialProfileRepository(db)

            sched = pub_repo.create_schedule(
                {
                    "website_id": site_id,
                    "social_profile_id": profile_id,
                    "social_post_id": post_id,
                    "platform_key": "facebook",
                    "scheduled_at": utc_now_naive() + timedelta(minutes=30),
                    "display_timezone": "Asia/Manila",
                    "status": "scheduled",
                }
            )
            assert sched.id >= 1

            job = pub_repo.create_job(
                {
                    "job_uuid": "11111111-1111-1111-1111-111111111111",
                    "idempotency_key": "p4-live-idem-1",
                    "publish_dedupe_key": "p4-live-dedupe-1",
                    "website_id": site_id,
                    "social_profile_id": profile_id,
                    "social_post_id": post_id,
                    "publishing_schedule_id": sched.id,
                    "platform_key": "facebook",
                    "publishing_method": "api",
                    "status": "queued",
                    "priority": 1,
                    "available_at": utc_now_naive() - timedelta(seconds=5),
                    "max_attempts": 3,
                    "timeout_seconds": 30,
                }
            )
            claimed = pub_repo.claim_job(job.id, worker_id="worker-mysql-1")
            assert claimed is not None
            assert claimed.status == "processing"
            assert claimed.attempt_count == 1

            # Second concurrent claim must return None while already processing
            assert pub_repo.claim_job(job.id, worker_id="worker-mysql-2") is None

            # Simulate timed-out worker heartbeat -> moves to verification_required
            stale_hb = utc_now_naive() - timedelta(minutes=30)
            pub_repo.update_job(job.id, {"heartbeat_at": stale_hb, "started_at": stale_hb})
            recovered = pub_repo.recover_stale_jobs(stale_minutes=15)
            assert len(recovered) == 1
            assert recovered[0].status == "verification_required"
            assert recovered[0].requires_verification is True

            rec = pub_repo.create_record(
                {
                    "website_id": site_id,
                    "website_name_snapshot": "Phase 4 Live",
                    "social_profile_id": profile_id,
                    "profile_name_snapshot": "P4 Legacy Manual Profile",
                    "platform_id": fb_id,
                    "platform_key": "facebook",
                    "platform_display_name": "Facebook Pages",
                    "social_post_id": post_id,
                    "publishing_job_id": job.id,
                    "publishing_method": "api",
                    "verification_status": "verified_after_timeout",
                    "outcome": "published",
                    "idempotency_key": "p4-live-idem-1",
                    "published_at": utc_now_naive(),
                    "external_post_id": "fb_page_1_999",
                    "published_url": "https://facebook.com/fb_page_1_999",
                    "caption_snapshot": "Existing approved draft",
                    "hashtags_snapshot_json": [],
                    "attempt_count": 1,
                    "last_http_status": 200,
                }
            )
            assert rec.id >= 1

            # Deleting post and social profile preserves PublicationRecord via ON DELETE SET NULL
            db.execute(text("DELETE FROM social_posts WHERE id = :id"), {"id": post_id})
            db.commit()
            assert prof_repo.delete(profile_id) is True
            rows, total = pub_repo.list_history(website_id=site_id)
            assert total == 1
            assert rows[0].social_post_id is None
            assert rows[0].social_profile_id is None
            assert rows[0].profile_name_snapshot == "P4 Legacy Manual Profile"

        # 4. Clean downgrade 20261128_0008 -> 20261128_0007 and re-upgrade back to 20261128_0008
        alembic_command.downgrade(alembic_cfg, "20261128_0007")
        with engine.connect() as conn:
            remaining = set(
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
            assert "publication_records" not in remaining
            assert "publishing_jobs" not in remaining

        alembic_command.upgrade(alembic_cfg, "20261128_0008")
        with engine.connect() as conn:
            reapplied = set(
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
            assert phase4_tables.issubset(reapplied)
    finally:
        engine.dispose()
