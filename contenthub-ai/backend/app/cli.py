from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import sys
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import check_database_connection, get_session_factory
from app.repositories.activity_log_repo import SQLAlchemyActivityLogRepository
from app.repositories.ai_repo import SQLAlchemyAiRepository
from app.repositories.category_repo import SQLAlchemyWebsiteCategoryRepository
from app.repositories.content_repo import SQLAlchemyContentRepository
from app.repositories.keyword_approval_repo import SQLAlchemyKeywordApprovalRepository
from app.repositories.media_repo import SQLAlchemyMediaRepository
from app.repositories.publishing_repo import SQLAlchemyPublishingRepository
from app.repositories.scan_log_repo import SQLAlchemyScanLogRepository
from app.repositories.session_repo import SQLAlchemySessionRepository
from app.repositories.settings_repo import SQLAlchemySettingsRepository
from app.repositories.social_post_repo import SQLAlchemySocialPostRepository
from app.repositories.social_profile_repo import SQLAlchemySocialProfileRepository
from app.repositories.user_repo import SQLAlchemyUserRepository
from app.repositories.website_repo import SQLAlchemyWebsiteRepository
from app.repositories.website_source_repo import SQLAlchemyWebsiteSourceConfigRepository
from app.services.ai.gemini import GeminiSdkProvider
from app.services.ai.generation_service import AiGenerationService
from app.services.auth_service import AuthService
from app.services.content_approval_service import ContentApprovalService
from app.services.indexing_service import IndexingService
from app.services.monitoring.health_service import HealthService
from app.services.publishers.registry import PublisherAdapterRegistry
from app.services.publishing_service import PublishingService
from app.services.scan_executor import ScanExecutorService
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from app.services.social_post_service import SocialPostService


def _build_ai_generation_service(db: Session, settings: Settings) -> AiGenerationService:
    activity_repo = SQLAlchemyActivityLogRepository(db)
    settings_repo = SQLAlchemySettingsRepository(db)
    return AiGenerationService(
        settings=settings,
        ai_repo=SQLAlchemyAiRepository(db),
        website_repo=SQLAlchemyWebsiteRepository(db),
        category_repo=SQLAlchemyWebsiteCategoryRepository(db),
        content_repo=SQLAlchemyContentRepository(db),
        social_profile_repo=SQLAlchemySocialProfileRepository(db),
        social_post_repo=SQLAlchemySocialPostRepository(db),
        activity_repo=activity_repo,
        health_service=HealthService(settings=settings),
        settings_service=SettingsService(
            settings=settings,
            settings_repo=settings_repo,
            activity_repo=activity_repo,
        ),
        provider_client=GeminiSdkProvider(),
        keyword_approval_repo=SQLAlchemyKeywordApprovalRepository(db),
    )


def _build_scan_executor(db: Session, settings: Settings) -> ScanExecutorService:
    activity_repo = SQLAlchemyActivityLogRepository(db)
    settings_repo = SQLAlchemySettingsRepository(db)
    website_repo = SQLAlchemyWebsiteRepository(db)
    content_repo = SQLAlchemyContentRepository(db)
    media_repo = SQLAlchemyMediaRepository(db)
    ai_repo = SQLAlchemyAiRepository(db)
    ai_gen_service = _build_ai_generation_service(db, settings)
    approval_service = ContentApprovalService(
        settings=settings,
        keyword_approval_repo=SQLAlchemyKeywordApprovalRepository(db),
        content_repo=content_repo,
        website_repo=website_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        ai_repo=ai_repo,
        provider_client=GeminiSdkProvider(),
        ai_generation_service=ai_gen_service,
    )
    return ScanExecutorService(
        settings=settings,
        website_repo=website_repo,
        source_config_repo=SQLAlchemyWebsiteSourceConfigRepository(db),
        content_repo=content_repo,
        scan_log_repo=SQLAlchemyScanLogRepository(db),
        media_repo=media_repo,
        activity_repo=activity_repo,
        health_service=HealthService(settings=settings),
        settings_service=SettingsService(
            settings=settings,
            settings_repo=settings_repo,
            activity_repo=activity_repo,
        ),
        fetcher=SafeHttpFetcher(settings=settings),
        ai_generation_service=ai_gen_service,
        approval_service=approval_service,
    )


def _build_publishing_service(db: Session, settings: Settings) -> PublishingService:
    activity_repo = SQLAlchemyActivityLogRepository(db)
    settings_repo = SQLAlchemySettingsRepository(db)
    website_repo = SQLAlchemyWebsiteRepository(db)
    content_repo = SQLAlchemyContentRepository(db)
    media_repo = SQLAlchemyMediaRepository(db)
    pub_repo = SQLAlchemyPublishingRepository(db)
    profile_repo = SQLAlchemySocialProfileRepository(db)
    post_repo = SQLAlchemySocialPostRepository(db)
    kw_repo = SQLAlchemyKeywordApprovalRepository(db)
    post_svc = SocialPostService(
        settings=settings,
        social_post_repo=post_repo,
        social_profile_repo=profile_repo,
        website_repo=website_repo,
        content_repo=content_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        publishing_repo=pub_repo,
        keyword_approval_repo=kw_repo,
    )
    return PublishingService(
        settings=settings,
        publishing_repo=pub_repo,
        social_post_repo=post_repo,
        social_profile_repo=profile_repo,
        website_repo=website_repo,
        content_repo=content_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        health_service=HealthService(settings=settings),
        settings_service=SettingsService(
            settings=settings,
            settings_repo=settings_repo,
            activity_repo=activity_repo,
        ),
        adapter_registry=PublisherAdapterRegistry(settings=settings),
        social_post_service=post_svc,
        keyword_approval_repo=kw_repo,
        ai_repo=SQLAlchemyAiRepository(db),
        fetcher=SafeHttpFetcher(settings=settings),
    )


def run_check_db(settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    diag = check_database_connection(settings=cfg)

    print(f"Database target : {diag.user}@{diag.host}:{diag.port}/{diag.database_name}")
    print(
        f"Connection pool : size={diag.pool_size}, "
        f"max_overflow={diag.max_overflow}, recycle={diag.pool_recycle}s"
    )
    if diag.uses_root_user:
        print(
            "WARNING         : DB_USER is 'root'. "
            "Use a dedicated least-privilege MySQL user in runtime."
        )

    if not diag.connected:
        print(f"Status          : UNAVAILABLE ({diag.error})")
        return 1

    print("Status          : CONNECTED")
    print(f"Server version  : {diag.server_version}")
    print(f"Character set   : {diag.character_set}")
    print(f"InnoDB enabled  : {diag.innodb_available}")
    print(f"Latency         : {diag.latency_ms} ms")

    if diag.character_set and diag.character_set.lower() != "utf8mb4":
        print("WARNING         : Database character set is not utf8mb4.")
    if diag.innodb_available is False:
        print("WARNING         : InnoDB storage engine is not reported as available.")
    return 0


def run_init_admin(
    *,
    email: str | None,
    display_name: str | None,
    password_env: str | None,
    auth_service: AuthService | None = None,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] = getpass.getpass,
) -> int:
    """Create the single administrator account interactively without any default password."""
    resolved_email = (email or input_fn("Administrator email: ")).strip()
    resolved_name = (display_name or input_fn("Administrator display name: ")).strip()

    if password_env:
        password = os.environ.get(password_env, "")
        if not password:
            print(
                f"Error: Environment variable '{password_env}' is empty or not set.",
                file=sys.stderr,
            )
            return 1
    else:
        password = secret_input_fn(
            "Administrator password (min 12 chars, upper/lower/digit/symbol): "
        )
        confirm = secret_input_fn("Confirm administrator password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            return 1

    if auth_service is not None:
        try:
            user = auth_service.initialize_admin(
                email=resolved_email,
                display_name=resolved_name,
                password=password,
            )
        except AppError as exc:
            print(f"Error: {exc.detail}", file=sys.stderr)
            return 1
        print(f"Administrator created: {user.email} (id={user.id})")
        return 0

    settings = get_settings()
    db = get_session_factory()()
    try:
        service = AuthService(
            settings=settings,
            user_repo=SQLAlchemyUserRepository(db),
            session_repo=SQLAlchemySessionRepository(db),
            activity_repo=SQLAlchemyActivityLogRepository(db),
            rate_limiter=SlidingWindowRateLimiter(),
        )
        user = service.initialize_admin(
            email=resolved_email,
            display_name=resolved_name,
            password=password,
        )
        print(f"Administrator created: {user.email} (id={user.id})")
        return 0
    except AppError as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(
            f"Database error ({type(exc).__name__}): "
            "verify MySQL connectivity and run `alembic upgrade head` first.",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()


def run_single_scan(
    *,
    scan_id: int,
    executor: ScanExecutorService | None = None,
) -> int:
    if executor is not None:
        result = executor.execute_scan(scan_id)
        print(
            f"Scan #{result.id}: status={result.status}, new={result.new_articles}, "
            f"updated={result.updated_articles}, failed={result.failed_articles}"
        )
        return 0 if result.status in {"completed", "partially_completed", "incomplete"} else 1

    settings = get_settings()
    db = get_session_factory()()
    try:
        service = _build_scan_executor(db, settings)
        result = service.execute_scan(scan_id)
        print(
            f"Scan #{result.id}: status={result.status}, new={result.new_articles}, "
            f"updated={result.updated_articles}, unchanged={result.unchanged_articles}, "
            f"failed={result.failed_articles}"
        )
        return 0 if result.status in {"completed", "partially_completed", "incomplete"} else 1
    except (AppError, SQLAlchemyError) as exc:
        print(f"Scan execution error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def run_due_scans(*, executor: ScanExecutorService | None = None) -> int:
    """Cron entrypoint: acquires a MySQL advisory lock and runs due website scans sequentially."""
    if executor is not None:
        summary = executor.run_due_scheduled_scans()
        print(
            f"Due scans summary: guardian={summary.guardian_status}, "
            f"paused={summary.paused_by_resource_guardian}, due={summary.due_websites_found}, "
            f"executed={summary.scans_executed}, succeeded={summary.scans_succeeded}, "
            f"failed={summary.scans_failed}"
        )
        return 0

    settings = get_settings()
    db = get_session_factory()()
    lock_name = "contenthub_due_scans_lock"
    lock_acquired = False
    try:
        got = db.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
        if got != 1:
            print("Another scheduled scan process already holds the MySQL advisory lock; exiting.")
            return 0
        lock_acquired = True

        service = _build_scan_executor(db, settings)
        summary = service.run_due_scheduled_scans()
        print(
            f"Due scans summary: guardian={summary.guardian_status}, "
            f"paused={summary.paused_by_resource_guardian}, "
            f"stale_recovered={summary.stale_recovered}, "
            f"due={summary.due_websites_found}, executed={summary.scans_executed}, "
            f"succeeded={summary.scans_succeeded}, failed={summary.scans_failed}, "
            f"skipped_locked={summary.skipped_locked}"
        )
        return 0
    except SQLAlchemyError as exc:
        print(f"Scheduled scan DB error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            with contextlib.suppress(SQLAlchemyError):
                db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
        db.close()


def run_single_ai_job(
    *,
    job_id: int,
    service: AiGenerationService | None = None,
) -> int:
    if service is not None:
        result = service.execute_job(job_id)
        print(
            f"AI Job #{result.id}: status={result.status}, "
            f"attempts={result.attempt_count}, error={result.error_message or 'none'}"
        )
        return 0 if result.status in {"completed", "partially_completed", "deferred"} else 1

    settings = get_settings()
    db = get_session_factory()()
    try:
        gen_service = _build_ai_generation_service(db, settings)
        result = gen_service.execute_job(job_id)
        print(
            f"AI Job #{result.id}: status={result.status}, "
            f"attempts={result.attempt_count}, error={result.error_message or 'none'}"
        )
        return 0 if result.status in {"completed", "partially_completed", "deferred"} else 1
    except (AppError, SQLAlchemyError) as exc:
        print(f"AI job execution error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def run_pending_ai_jobs(*, limit: int = 10, service: AiGenerationService | None = None) -> int:
    if service is not None:
        results = service.run_pending_jobs(limit=limit)
        print(f"Processed {len(results)} pending/deferred AI generation job(s).")
        return 0

    settings = get_settings()
    db = get_session_factory()()
    lock_name = "contenthub_ai_jobs_lock"
    lock_acquired = False
    try:
        got = db.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
        if got != 1:
            print("Another AI worker already holds the MySQL advisory lock; exiting.")
            return 0
        lock_acquired = True
        gen_service = _build_ai_generation_service(db, settings)
        results = gen_service.run_pending_jobs(limit=limit)
        print(f"Processed {len(results)} pending/deferred AI generation job(s).")
        return 0
    except SQLAlchemyError as exc:
        print(f"AI job worker DB error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            with contextlib.suppress(SQLAlchemyError):
                db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
        db.close()


def run_single_publish_job(
    *,
    job_id: int,
    service: PublishingService | None = None,
) -> int:
    if service is not None:
        result = service.execute_job(job_id)
        print(
            f"Publish Job #{result.id}: status={result.status}, "
            f"attempts={result.attempt_count}, error={result.error_message or 'none'}"
        )
        return 0 if result.status in {"published", "deferred"} else 1

    settings = get_settings()
    db = get_session_factory()()
    try:
        pub_service = _build_publishing_service(db, settings)
        result = pub_service.execute_job(job_id)
        print(
            f"Publish Job #{result.id}: status={result.status}, "
            f"attempts={result.attempt_count}, error={result.error_message or 'none'}"
        )
        return 0 if result.status in {"published", "deferred"} else 1
    except (AppError, SQLAlchemyError) as exc:
        print(f"Publishing job execution error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def run_due_publishes(*, limit: int = 10, service: PublishingService | None = None) -> int:
    if service is not None:
        results = service.run_due_jobs(limit=limit)
        print(f"Processed {len(results)} due publishing job(s).")
        return 0

    settings = get_settings()
    db = get_session_factory()()
    lock_name = "contenthub_publishing_jobs_lock"
    lock_acquired = False
    try:
        got = db.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
        if got != 1:
            print("Another publishing worker already holds the MySQL advisory lock; exiting.")
            return 0
        lock_acquired = True
        pub_service = _build_publishing_service(db, settings)
        results = pub_service.run_due_jobs(limit=limit)
        print(f"Processed {len(results)} due publishing job(s).")
        return 0
    except SQLAlchemyError as exc:
        print(f"Publishing worker DB error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            with contextlib.suppress(SQLAlchemyError):
                db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
        db.close()


def run_indexing_job(*, job_id: int) -> int:
    settings = get_settings()
    db = get_session_factory()()
    try:
        service = IndexingService(
            db=db,
            settings=settings,
            health_service=HealthService(settings=settings),
        )
        job = service.execute_job(job_id)
        print(
            f"Indexing Job #{job.id}: status={job.status}, "
            f"processed={job.processed_count}/{job.requested_count}, "
            f"indexed={job.indexed_count}, ready={job.ready_count}, "
            f"skipped={job.skipped_count}, failed={job.failed_count}"
        )
        return 0 if job.status in {"completed", "deferred"} else 1
    except (AppError, SQLAlchemyError) as exc:
        print(f"Indexing job execution error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def run_daily_indexing(*, service: IndexingService | None = None) -> int:
    if service is not None:
        summary = service.run_daily_indexing(execute_inline=True)
        print(
            f"Daily indexing summary: state={summary['state']}, "
            f"processed={summary['processed']}/{summary['total']}, "
            f"indexed={summary['indexed']}, ready={summary['ready']}, "
            f"skipped={summary['skipped']}, failed={summary['failed']}"
        )
        return 0

    settings = get_settings()
    db = get_session_factory()()
    lock_name = "contenthub_daily_indexing_lock"
    lock_acquired = False
    try:
        got = db.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
        if got != 1:
            print("Another indexing worker already holds the MySQL advisory lock; exiting.")
            return 0
        lock_acquired = True
        idx_service = IndexingService(
            db=db,
            settings=settings,
            health_service=HealthService(settings=settings),
        )
        summary = idx_service.run_daily_indexing(execute_inline=True)
        print(
            f"Daily indexing summary: state={summary['state']}, "
            f"processed={summary['processed']}/{summary['total']}, "
            f"indexed={summary['indexed']}, ready={summary['ready']}, "
            f"skipped={summary['skipped']}, failed={summary['failed']}"
        )
        return 0
    except AppError as exc:
        print(f"Daily indexing skipped: {exc.detail}")
        return 0
    except SQLAlchemyError as exc:
        print(f"Daily indexing DB error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            with contextlib.suppress(SQLAlchemyError):
                db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="ContentHub AI administration & scanner CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "check-db",
        help="Verify MySQL connectivity, version, InnoDB, and utf8mb4.",
    )

    init_parser = subparsers.add_parser(
        "init-admin",
        help="Initialize the single administrator account (no default credentials).",
    )
    init_parser.add_argument("--email", help="Administrator email address.")
    init_parser.add_argument("--name", dest="display_name", help="Administrator display name.")
    init_parser.add_argument(
        "--password-env",
        help="Optional environment variable name holding the password.",
    )

    run_scan_parser = subparsers.add_parser(
        "run-scan",
        help="Claim and execute a single pending website scan by ID.",
    )
    run_scan_parser.add_argument("--scan-id", type=int, required=True, help="WebsiteScanLog ID.")

    subparsers.add_parser(
        "run-due-scans",
        help="Run due scheduled website scans sequentially under a MySQL advisory lock.",
    )

    run_ai_parser = subparsers.add_parser(
        "run-ai-job",
        help="Claim and execute a single queued or deferred AI generation job by ID.",
    )
    run_ai_parser.add_argument("--job-id", type=int, required=True, help="AiGenerationJob ID.")

    run_pending_ai = subparsers.add_parser(
        "run-pending-ai-jobs",
        help="Process queued and retryable deferred AI generation jobs under MySQL advisory lock.",
    )
    run_pending_ai.add_argument("--limit", type=int, default=10, help="Max jobs per pass.")

    run_pub_parser = subparsers.add_parser(
        "run-publish-job",
        help="Claim and execute a single queued publishing job by ID.",
    )
    run_pub_parser.add_argument("--job-id", type=int, required=True, help="PublishingJob ID.")

    run_due_pub = subparsers.add_parser(
        "run-due-publishes",
        help="Process due scheduled/queued publishing jobs under a MySQL advisory lock.",
    )
    run_due_pub.add_argument("--limit", type=int, default=10, help="Max jobs per pass.")
    run_indexing = subparsers.add_parser(
        "run-indexing-job",
        help="Execute a single persistent Google indexing job.",
    )
    run_indexing.add_argument("--job-id", type=int, required=True, help="IndexingJob ID.")
    subparsers.add_parser(
        "run-daily-indexing",
        help="Run daily Google indexing batch across all active websites under an advisory lock.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-db":
        return run_check_db()
    if args.command == "init-admin":
        return run_init_admin(
            email=args.email,
            display_name=args.display_name,
            password_env=args.password_env,
        )
    if args.command == "run-scan":
        return run_single_scan(scan_id=args.scan_id)
    if args.command == "run-due-scans":
        return run_due_scans()
    if args.command == "run-ai-job":
        return run_single_ai_job(job_id=args.job_id)
    if args.command == "run-pending-ai-jobs":
        return run_pending_ai_jobs(limit=args.limit)
    if args.command == "run-publish-job":
        return run_single_publish_job(job_id=args.job_id)
    if args.command == "run-due-publishes":
        return run_due_publishes(limit=args.limit)
    if args.command == "run-indexing-job":
        return run_indexing_job(job_id=args.job_id)
    if args.command == "run-daily-indexing":
        return run_daily_indexing()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
